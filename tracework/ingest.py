"""Trusted file ingestion; normalization occurs in a bounded child process."""

import json
import re
import subprocess
import sys
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from . import store

MAX_BYTES = 50 * 1024 * 1024
MAX_ROWS = 500000


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def preview_rows(table, limit=30):
    def bounded(value):
        if isinstance(value, str) and len(value) > 2000:
            return value[:2000] + "… [preview truncated]"
        if isinstance(value, dict):
            return {key: bounded(item) for key, item in value.items()}
        if isinstance(value, list):
            return [bounded(item) for item in value[:50]]
        return value

    return [bounded(row) for row in table.slice(0, limit).to_pylist()]


def profile_table(table):
    con = duckdb.connect(config={"memory_limit": "256MB", "threads": 2})
    con.register("data", table)
    columns = []
    for field in table.schema:
        col = identifier(field.name)
        count, distinct = con.execute(
            f"SELECT count(*)-count({col}), count(DISTINCT {col}) FROM data"
        ).fetchone()
        numeric = any(t in str(field.type) for t in ("int", "float", "double", "decimal"))
        stats = {}
        if numeric:
            values = con.execute(f"SELECT min({col}),max({col}),avg({col}) FROM data").fetchone()
            stats = dict(zip(("min", "max", "mean"), values))
        columns.append(
            {
                "name": field.name,
                "type": str(field.type),
                "nullable": field.nullable,
                "missing": count,
                "distinct": distinct,
                **stats,
            }
        )
    con.close()
    return {"rows": table.num_rows, "columns": columns, "sample": preview_rows(table)}


def normalize(source, target):
    # This process sees only an app-selected upload path; no model SQL runs here.
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))
    if source.suffix == ".parquet":
        meta = pq.read_metadata(source)
        if meta.num_rows > MAX_ROWS or meta.num_columns > 100:
            raise ValueError("Upload exceeds 500,000 rows or 100 columns")
        if sum(meta.row_group(i).total_byte_size for i in range(meta.num_row_groups)) > 256 * 1024 * 1024:
            raise ValueError("Expanded Parquet exceeds 256 MiB")
        table = pq.read_table(source)
    else:
        con = duckdb.connect(
            config={
                "memory_limit": "256MB",
                "threads": 2,
                "autoinstall_known_extensions": False,
                "autoload_known_extensions": False,
            }
        )
        table = con.execute(
            "SELECT * FROM read_csv(?, header=true, sample_size=-1) LIMIT ?", [str(source), MAX_ROWS + 1]
        ).to_arrow_table()
        con.close()
    if table.num_rows > MAX_ROWS or table.num_columns > 100:
        raise ValueError("Upload exceeds 500,000 rows or 100 columns")
    if not table.num_columns or len(set(n.lower() for n in table.column_names)) != table.num_columns:
        raise ValueError("Columns must have unique names (case insensitive)")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", n) for n in table.column_names):
        raise ValueError("Column names must be SQL identifiers: letters, numbers and underscores")
    profile = profile_table(table)
    pq.write_table(table, target)
    target.with_suffix(".json").write_text(store.dumps(profile))


def ingest(workspace_id, name, filename, data):
    store.require_workspace(workspace_id)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name):
        raise ValueError("Source name must be lowercase letters, numbers and underscores")
    suffix = Path(filename).suffix.lower()
    if suffix not in (".csv", ".parquet"):
        raise ValueError("Only CSV and Parquet are supported")
    if len(data) > MAX_BYTES or not data:
        raise ValueError("Upload must contain data and be at most 50 MiB")
    sha = store.digest(data)
    existing = store.one(
        "SELECT v.* FROM source_versions v JOIN sources s ON s.id=v.source_id WHERE s.workspace_id=? AND s.name=? AND v.hash=?",
        (workspace_id, name, sha),
    )
    if existing:
        return existing
    folder = store.root() / "uploads" / workspace_id / store.uid()
    folder.mkdir(parents=True)
    original = folder / ("original" + suffix)
    normalized = folder / "data.parquet"
    original.write_bytes(data)
    original.chmod(0o444)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "tracework.ingest", str(original), str(normalized)],
            capture_output=True,
            text=True,
            timeout=35,
            env=child_env(),
        )
        if result.returncode:
            raise ValueError(
                "Ingestion failed: "
                + store.safe_error(result.stderr.splitlines()[-1] if result.stderr else "worker exited")
            )
        profile = json.loads(normalized.with_suffix(".json").read_text())
        normalized.chmod(0o444)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Ingestion exceeded 35 seconds") from exc
    schema = [{k: c[k] for k in ("name", "type", "nullable")} for c in profile["columns"]]
    with store.transaction() as db:
        source = db.execute(
            "SELECT id FROM sources WHERE workspace_id=? AND name=?", (workspace_id, name)
        ).fetchone()
        sid = source["id"] if source else store.uid()
        if not source:
            db.execute("INSERT INTO sources VALUES(?,?,?)", (sid, workspace_id, name))
        existing = db.execute(
            "SELECT * FROM source_versions WHERE source_id=? AND hash=?", (sid, sha)
        ).fetchone()
        if existing:
            return store.decode(existing)
        did, vid = store.uid(), store.uid()
        db.execute(
            "INSERT INTO datasets VALUES(?,?,?,?,?,?,?)",
            (
                did,
                workspace_id,
                name,
                str(normalized.relative_to(store.root())),
                store.dumps(schema),
                store.dumps(profile),
                profile["rows"],
            ),
        )
        db.execute(
            "INSERT INTO source_versions VALUES(?,?,?,?,?,?,?)",
            (vid, sid, did, sha, Path(filename).name, str(original.relative_to(store.root())), store.now()),
        )
    return store.one("SELECT * FROM source_versions WHERE id=?", (vid,))


def child_env():
    import os

    return {
        k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TMPDIR", "LANG", "VIRTUAL_ENV")
    } | {"TRACEWORK_DATA_DIR": str(store.root())}


def sources(workspace_id):
    store.require_workspace(workspace_id)
    records = store.all_rows("SELECT * FROM sources WHERE workspace_id=? ORDER BY name", (workspace_id,))
    for source in records:
        source["versions"] = store.all_rows(
            "SELECT v.*,d.rows,d.schema_json,d.profile_json FROM source_versions v JOIN datasets d ON d.id=v.dataset_id WHERE source_id=? ORDER BY created_at DESC",
            (source["id"],),
        )
    return records


if __name__ == "__main__":
    normalize(Path(sys.argv[1]), Path(sys.argv[2]))
