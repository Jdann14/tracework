import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pyarrow.parquet as pq
from fastapi import FastAPI, UploadFile, File, Form, Query, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import Field

from . import store
from .compare import compare_runs
from .demo import load_batch
from .ingest import MAX_BYTES, ingest, sources
from .models import StrictModel, PipelineSpec, RunRequest
from .pipelines import version, create_version, approve, enqueue, get_run
from .worker import finish_run


@asynccontextmanager
async def lifespan(app):
    store.init()
    yield


app = FastAPI(title="Tracework", version="0.1.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=["127.0.0.1","localhost","testserver"])


@app.middleware("http")
async def local_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin and origin not in {"http://127.0.0.1:4318","http://localhost:4318","http://127.0.0.1:8000","http://localhost:8000"}:
        return JSONResponse({"detail":"Cross-origin access rejected"},status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({"detail":store.safe_error(exc)},status_code=400)


@app.exception_handler(LookupError)
async def missing(request, exc):
    return JSONResponse({"detail":store.safe_error(exc)},status_code=404)


class NewWorkspace(StrictModel):
    name: str = Field(min_length=1,max_length=120)


class Proposal(StrictModel):
    spec: PipelineSpec
    parent_id: str | None = None


class Question(StrictModel):
    question: str = Field(min_length=1,max_length=8000)
    provider: Literal["demo","openai"] = "demo"
    base_version_id: str | None = None
    failed_run_id: str | None = None


@app.get("/api/health")
def health():
    worker = store.one("SELECT * FROM worker_state WHERE id=1")
    age = (datetime.now(timezone.utc)-datetime.fromisoformat(worker["heartbeat"])).total_seconds() if worker else None
    return {"status":"ok","worker_online":age is not None and age<10,"worker_heartbeat":worker["heartbeat"] if worker else None,"provider":os.getenv("TRACEWORK_PROVIDER","demo"),"openai_configured":bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL"))}


@app.get("/api/workspaces")
def list_workspaces():
    return store.all_rows("SELECT * FROM workspaces ORDER BY created_at")


@app.post("/api/workspaces")
def new_workspace(body: NewWorkspace):
    return store.create_workspace(body.name.strip())


@app.get("/api/workspaces/{wid}")
def workspace_detail(wid: str):
    store.require_workspace(wid)
    pipelines = store.all_rows("SELECT * FROM pipelines WHERE workspace_id=? ORDER BY created_at DESC",(wid,))
    for pipeline in pipelines:
        pipeline["versions"] = store.all_rows("SELECT v.*,a.approved_at FROM pipeline_versions v LEFT JOIN approvals a ON a.version_id=v.id WHERE pipeline_id=? ORDER BY number DESC",(pipeline["id"],))
    investigations = store.all_rows("SELECT * FROM investigations WHERE workspace_id=? ORDER BY created_at",(wid,))
    for investigation in investigations:
        investigation["events"] = store.all_rows("SELECT * FROM tool_events WHERE investigation_id=? ORDER BY id",(investigation["id"],))
    return {"sources":sources(wid),"pipelines":pipelines,"runs":store.all_rows("SELECT * FROM runs WHERE workspace_id=? ORDER BY created_at DESC",(wid,)),"investigations":investigations}


@app.post("/api/workspaces/{wid}/sources")
def upload_source(wid: str, name: str = Form(...), file: UploadFile = File(...)):
    # Starlette spools uploads to disk. Limit retained bytes before normalization.
    data = file.file.read(MAX_BYTES+1)
    return ingest(wid,name,file.filename or "upload.csv",data)


@app.get("/api/workspaces/{wid}/datasets/{did}")
def dataset(wid: str, did: str, offset: int = Query(0,ge=0), limit: int = Query(50,ge=1,le=100)):
    record = store.one("SELECT * FROM datasets WHERE id=? AND workspace_id=?",(did,wid))
    if not record:
        raise LookupError("Dataset not found")
    table = pq.read_table(store.local_path(record["path"]))
    record.pop("path")
    return {**record,"data":table.slice(offset,limit).to_pylist(),"offset":offset,"limit":limit}


@app.get("/api/workspaces/{wid}/datasets/{did}/download")
def download(wid: str, did: str, format: Literal["parquet","csv"] = "parquet"):
    record = store.one("SELECT * FROM datasets WHERE id=? AND workspace_id=?",(did,wid))
    if not record:
        raise LookupError("Dataset not found")
    path = store.local_path(record["path"])
    if format == "parquet":
        return FileResponse(path,filename=record["name"]+".parquet",media_type="application/octet-stream")
    import pyarrow as pa
    import pyarrow.csv as pc
    stream = pa.BufferOutputStream()
    pc.write_csv(pq.read_table(path),stream)
    return Response(stream.getvalue().to_pybytes(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="{record["name"]}.csv"'})


@app.post("/api/workspaces/{wid}/pipelines")
def propose(wid: str, body: Proposal):
    return create_version(wid,body.spec,body.parent_id)


@app.post("/api/workspaces/{wid}/versions/{vid}/approve")
def approval(wid: str, vid: str):
    return approve(wid,vid)


@app.post("/api/workspaces/{wid}/runs")
def run(wid: str, body: RunRequest):
    return enqueue(wid,body)


@app.get("/api/workspaces/{wid}/runs/{rid}")
def run_detail(wid: str, rid: str):
    return get_run(wid,rid)


@app.post("/api/workspaces/{wid}/runs/{rid}/cancel")
def cancel(wid: str, rid: str):
    current = get_run(wid,rid)
    if current["status"] == "queued":
        finish_run(rid,"cancelled","Cancelled before execution")
    elif current["status"] == "running":
        store.execute("UPDATE runs SET cancel_requested=1 WHERE id=?",(rid,))
    return get_run(wid,rid)


@app.get("/api/workspaces/{wid}/compare")
def compare(wid: str, left: str, right: str, key: str = "channel", metric: str = "contribution_profit"):
    return compare_runs(wid,left,right,key,metric)


@app.post("/api/workspaces/{wid}/investigations")
def ask(wid: str, body: Question):
    store.require_workspace(wid)
    if body.base_version_id:
        version(wid,body.base_version_id)
    if body.failed_run_id:
        failed = get_run(wid,body.failed_run_id)
        if failed["status"] != "failed" or failed["version_id"] != body.base_version_id:
            raise ValueError("Repair must reference a failed run of the selected base version")
    if body.provider == "openai" and not (os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL")):
        raise ValueError("Real provider requires OPENAI_API_KEY and OPENAI_MODEL")
    iid = store.uid()
    store.execute("INSERT INTO investigations(id,workspace_id,question,provider,status,base_version_id,failed_run_id,created_at) VALUES(?,?,?,?,?,?,?,?)",(iid,wid,body.question,body.provider,"queued",body.base_version_id,body.failed_run_id,store.now()))
    return store.one("SELECT * FROM investigations WHERE id=?",(iid,))


@app.post("/api/workspaces/{wid}/demo/{batch}")
def demo_batch(wid: str, batch: int):
    if batch not in (1,2):
        raise ValueError("Choose demo batch 1 or 2")
    return {"batch":batch,"inputs":load_batch(wid,batch)}


static = Path(__file__).resolve().parent.parent / "web" / "dist"
if static.exists():
    app.mount("/",StaticFiles(directory=static,html=True),name="web")
