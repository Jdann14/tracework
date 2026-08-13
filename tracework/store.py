"""SQLite owns identities and transactions; immutable files own table data."""
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, default=str, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else dumps(value).encode()).hexdigest()


def root():
    return Path(os.environ.get("TRACEWORK_DATA_DIR", ".tracework")).resolve()


def safe_error(error):
    text = str(error)
    for key, value in os.environ.items():
        if any(word in key.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")) and len(value) > 5:
            text = text.replace(value, "[redacted]")
    return re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", text)[:2000]


SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,workspace_id TEXT REFERENCES workspaces(id),name TEXT NOT NULL,UNIQUE(workspace_id,name));
CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY,workspace_id TEXT REFERENCES workspaces(id),name TEXT NOT NULL,path TEXT NOT NULL,schema_json TEXT NOT NULL,profile_json TEXT NOT NULL,rows INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS source_versions(id TEXT PRIMARY KEY,source_id TEXT REFERENCES sources(id),dataset_id TEXT REFERENCES datasets(id),hash TEXT NOT NULL,original_name TEXT NOT NULL,original_path TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(source_id,hash));
CREATE TABLE IF NOT EXISTS pipelines(id TEXT PRIMARY KEY,workspace_id TEXT REFERENCES workspaces(id),title TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_versions(id TEXT PRIMARY KEY,pipeline_id TEXT REFERENCES pipelines(id),number INTEGER NOT NULL,parent_id TEXT REFERENCES pipeline_versions(id),spec_json TEXT NOT NULL,hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(pipeline_id,number));
CREATE TABLE IF NOT EXISTS approvals(version_id TEXT PRIMARY KEY REFERENCES pipeline_versions(id),approved_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,workspace_id TEXT REFERENCES workspaces(id),version_id TEXT REFERENCES pipeline_versions(id),request_key TEXT NOT NULL,request_hash TEXT NOT NULL,inputs_json TEXT NOT NULL,parameters_json TEXT NOT NULL,settings_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,heartbeat TEXT,error TEXT,cancel_requested INTEGER DEFAULT 0,UNIQUE(workspace_id,request_key));
CREATE TABLE IF NOT EXISTS step_executions(run_id TEXT REFERENCES runs(id),name TEXT,status TEXT NOT NULL,started_at TEXT,finished_at TEXT,error TEXT,PRIMARY KEY(run_id,name));
CREATE TABLE IF NOT EXISTS checks(id TEXT PRIMARY KEY,run_id TEXT REFERENCES runs(id),step TEXT NOT NULL,name TEXT NOT NULL,severity TEXT NOT NULL,status TEXT NOT NULL,violations INTEGER,sql TEXT NOT NULL,sample_json TEXT NOT NULL,error TEXT);
CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,run_id TEXT REFERENCES runs(id),step TEXT NOT NULL,dataset_id TEXT REFERENCES datasets(id),hash TEXT NOT NULL,UNIQUE(run_id,step));
CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY,run_id TEXT REFERENCES runs(id),artifact_id TEXT REFERENCES artifacts(id),title TEXT NOT NULL,detail TEXT NOT NULL,evidence_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT REFERENCES runs(id),step TEXT,message TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS investigations(id TEXT PRIMARY KEY,workspace_id TEXT REFERENCES workspaces(id),question TEXT NOT NULL,provider TEXT NOT NULL,status TEXT NOT NULL,base_version_id TEXT REFERENCES pipeline_versions(id),failed_run_id TEXT REFERENCES runs(id),version_id TEXT REFERENCES pipeline_versions(id),message TEXT,created_at TEXT NOT NULL,heartbeat TEXT,error TEXT);
CREATE TABLE IF NOT EXISTS tool_events(id INTEGER PRIMARY KEY AUTOINCREMENT,investigation_id TEXT REFERENCES investigations(id),tool TEXT NOT NULL,arguments_json TEXT NOT NULL,response_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS worker_state(id INTEGER PRIMARY KEY CHECK(id=1),heartbeat TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_sources BEFORE UPDATE ON source_versions BEGIN SELECT RAISE(ABORT,'Source versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_pipelines BEFORE UPDATE ON pipeline_versions BEGIN SELECT RAISE(ABORT,'Pipeline versions are immutable'); END;
"""


def connect():
    root().mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root() / "metadata.sqlite", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init():
    with connect() as db:
        db.executescript(SCHEMA)


@contextmanager
def transaction():
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def decode(row):
    if row is None:
        return None
    return {k.removesuffix("_json"): json.loads(v) if k.endswith("_json") else v for k, v in dict(row).items()}


def all_rows(sql, args=()):
    with connect() as db:
        return [decode(r) for r in db.execute(sql, args).fetchall()]


def one(sql, args=()):
    with connect() as db:
        return decode(db.execute(sql, args).fetchone())


def execute(sql, args=()):
    with connect() as db:
        db.execute(sql, args)


def require_workspace(workspace_id):
    if not one("SELECT id FROM workspaces WHERE id=?", (workspace_id,)):
        raise LookupError("Workspace not found")


def create_workspace(name):
    wid = uid()
    execute("INSERT INTO workspaces VALUES(?,?,?)", (wid, name, now()))
    return one("SELECT * FROM workspaces WHERE id=?", (wid,))


def log(run_id, message, step=None):
    execute("INSERT INTO logs(run_id,step,message,created_at) VALUES(?,?,?,?)", (run_id, step, safe_error(message), now()))


def local_path(relative):
    path = (root() / relative).resolve()
    if not path.is_relative_to(root()):
        raise ValueError("Artifact path escaped storage")
    return path
