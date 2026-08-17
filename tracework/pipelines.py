from . import store
from .models import PipelineSpec, RunRequest
from .sql import order_steps


def version(workspace_id, version_id):
    result = store.one("SELECT v.*,p.workspace_id FROM pipeline_versions v JOIN pipelines p ON p.id=v.pipeline_id WHERE v.id=? AND p.workspace_id=?", (version_id, workspace_id))
    if not result:
        raise LookupError("Pipeline version not found in this workspace")
    result["approved"] = bool(store.one("SELECT * FROM approvals WHERE version_id=?", (version_id,)))
    return result


def create_version(workspace_id, spec: PipelineSpec, parent_id=None):
    store.require_workspace(workspace_id)
    order_steps(spec)
    parent = version(workspace_id, parent_id) if parent_id else None
    with store.transaction() as db:
        pid = parent["pipeline_id"] if parent else store.uid()
        if not parent:
            db.execute("INSERT INTO pipelines VALUES(?,?,?,?)", (pid, workspace_id, spec.title, store.now()))
        number = db.execute("SELECT coalesce(max(number),0)+1 FROM pipeline_versions WHERE pipeline_id=?", (pid,)).fetchone()[0]
        vid = store.uid()
        raw = spec.model_dump()
        db.execute("INSERT INTO pipeline_versions VALUES(?,?,?,?,?,?,?)", (vid, pid, number, parent_id, store.dumps(raw), store.digest(raw), store.now()))
    return version(workspace_id, vid)


def approve(workspace_id, version_id):
    version(workspace_id, version_id)
    store.execute("INSERT OR IGNORE INTO approvals VALUES(?,?)", (version_id, store.now()))
    return version(workspace_id, version_id)


def resolve_inputs(workspace_id, inputs):
    resolved = {}
    for name, vid in inputs.items():
        row = store.one("SELECT v.*,s.name,d.path,d.schema_json,d.rows FROM source_versions v JOIN sources s ON s.id=v.source_id JOIN datasets d ON d.id=v.dataset_id WHERE v.id=? AND s.workspace_id=?", (vid, workspace_id))
        if not row:
            raise ValueError(f"Input {name} does not belong to this workspace")
        resolved[name] = row
    if sum(r["rows"] for r in resolved.values()) > 1000000:
        raise ValueError("A run supports at most one million total source rows")
    return resolved


def enqueue(workspace_id, request: RunRequest):
    ver = version(workspace_id, request.version_id)
    if not ver["approved"]:
        raise ValueError("Approve this exact pipeline version before running")
    spec = PipelineSpec.model_validate(ver["spec"])
    if set(request.inputs) != {s.name for s in spec.sources}:
        raise ValueError("Explicitly map every pipeline source input, with no extras")
    resolve_inputs(workspace_id, request.inputs)
    if set(request.parameters) - set(spec.parameters):
        raise ValueError("Unknown pipeline parameter")
    params = spec.parameters | request.parameters
    payload = request.model_dump(exclude={"request_key"}) | {"parameters": params}
    sha = store.digest(payload)
    with store.transaction() as db:
        existing = db.execute("SELECT * FROM runs WHERE workspace_id=? AND request_key=?", (workspace_id, request.request_key)).fetchone()
        if existing:
            if existing["request_hash"] != sha:
                raise ValueError("Request key already used for different inputs or settings")
            return store.decode(existing)
        rid = store.uid()
        db.execute("INSERT INTO runs(id,workspace_id,version_id,request_key,request_hash,inputs_json,parameters_json,settings_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (rid, workspace_id, request.version_id, request.request_key, sha, store.dumps(request.inputs), store.dumps(params), store.dumps(request.settings.model_dump()), "queued", store.now()))
        for step in spec.steps:
            db.execute("INSERT INTO step_executions(run_id,name,status) VALUES(?,?,?)", (rid, step.name, "queued"))
    store.log(rid, "Queued with explicit source versions; transformation code is frozen.")
    return store.one("SELECT * FROM runs WHERE id=?", (rid,))


def get_run(workspace_id, run_id):
    run = store.one("SELECT * FROM runs WHERE id=? AND workspace_id=?", (run_id, workspace_id))
    if not run:
        raise LookupError("Run not found in this workspace")
    for name, table in (("steps", "step_executions"), ("checks", "checks"), ("logs", "logs"), ("findings", "findings")):
        run[name] = store.all_rows(f"SELECT * FROM {table} WHERE run_id=?", (run_id,))
    run["artifacts"] = store.all_rows("SELECT a.*,d.rows,d.schema_json,d.profile_json FROM artifacts a JOIN datasets d ON a.dataset_id=d.id WHERE run_id=?", (run_id,))
    run["version"] = version(workspace_id, run["version_id"])
    run["resolved_inputs"] = resolve_inputs(workspace_id, run["inputs"])
    return run
