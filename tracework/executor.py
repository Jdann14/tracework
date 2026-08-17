"""Trusted executor child. It never receives provider credentials or executes Python from users."""
import resource
import sys
import pyarrow.parquet as pq
from . import store
from .engine import DuckDBBackend
from .ingest import profile_table
from .models import PipelineSpec, Settings
from .pipelines import resolve_inputs, version
from .sql import order_steps


def run_pipeline(run_id):
    run = store.one("SELECT * FROM runs WHERE id=?", (run_id,))
    settings = Settings.model_validate(run["settings"])
    resource.setrlimit(resource.RLIMIT_CPU, (settings.timeout_seconds + 5, settings.timeout_seconds + 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))
    spec = PipelineSpec.model_validate(version(run["workspace_id"], run["version_id"])["spec"])
    inputs = resolve_inputs(run["workspace_id"], run["inputs"])
    current, engine = None, None
    try:
        for source in spec.sources:
            schema = {c["name"]: c["type"] for c in inputs[source.name]["schema"]}
            missing = set(source.columns) - set(schema)
            changed = {k: (source.columns[k], schema[k]) for k in source.columns if k in schema and source.columns[k] != schema[k]}
            if missing or changed:
                raise ValueError(f"Source contract failed for {source.name}: missing columns {sorted(missing)}; changed types {changed}. Map a compatible source version or explicitly revise the recipe.")
        engine = DuckDBBackend(inputs, settings)
        store.log(run_id, "Approved inputs materialized. External access disabled; engine configuration locked.")
        for step in order_steps(spec):
            current = step.name
            store.execute("UPDATE step_executions SET status='running',started_at=? WHERE run_id=? AND name=?", (store.now(), run_id, current))
            store.log(run_id, "Executing transformation", current)
            table = engine.query(step.sql, set(step.depends_on), run["parameters"])
            engine.materialize(current, table)
            artifact_id = save_artifact(run, current, table)
            failed = False
            for check in step.checks:
                result = engine.query(check.sql, set(step.depends_on) | {current}, run["parameters"])
                n = result.num_rows
                status = "passed" if n == 0 else "failed"
                store.execute("INSERT INTO checks VALUES(?,?,?,?,?,?,?,?,?,?)", (store.uid(), run_id, current, check.name, check.severity, status, n, check.sql, store.dumps(result.slice(0, 20).to_pylist()), None))
                store.log(run_id, f"{check.severity}: {check.name} — {n} violating rows", current)
                failed |= bool(n and check.severity == "blocking")
            if failed:
                raise ValueError(f"Blocking data-quality checks failed in {current}. Inspect violation samples; this attempt and its artifacts are preserved.")
            store.execute("UPDATE step_executions SET status='successful',finished_at=? WHERE run_id=? AND name=?", (store.now(), run_id, current))
            store.log(run_id, f"Materialized {table.num_rows:,} rows", current)
            if current == spec.output:
                create_finding(run_id, artifact_id, table, current)
        store.execute("UPDATE runs SET status='successful',finished_at=? WHERE id=? AND status='running'", (store.now(), run_id))
        store.log(run_id, "Run completed. Findings link to the executed output.")
    except Exception as exc:
        error = store.safe_error(exc)
        if current:
            store.execute("UPDATE step_executions SET status='failed',error=?,finished_at=? WHERE run_id=? AND name=?", (error, store.now(), run_id, current))
        store.execute("UPDATE step_executions SET status='skipped',finished_at=? WHERE run_id=? AND status='queued'", (store.now(), run_id))
        store.execute("UPDATE runs SET status='failed',error=?,finished_at=? WHERE id=? AND status='running'", (error, store.now(), run_id))
        store.log(run_id, error, current)
    finally:
        if engine:
            engine.close()


def save_artifact(run, step, table):
    folder = store.root() / "runs" / run["id"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{step}.parquet"
    pq.write_table(table, path)
    path.chmod(0o444)
    profile = profile_table(table)
    schema = [{k: c[k] for k in ("name", "type", "nullable")} for c in profile["columns"]]
    aid, did = store.uid(), store.uid()
    with store.transaction() as db:
        db.execute("INSERT INTO datasets VALUES(?,?,?,?,?,?,?)", (did, run["workspace_id"], step, str(path.relative_to(store.root())), store.dumps(schema), store.dumps(profile), table.num_rows))
        db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?)", (aid, run["id"], step, did, store.digest(path.read_bytes())))
    return aid


def create_finding(run_id, artifact_id, table, step):
    if not table.num_rows:
        title, detail, evidence = "The query returned no rows", "Review filters and source coverage.", {"step": step, "row_count": 0}
    else:
        row = table.slice(0, 1).to_pylist()[0]
        if "channel" in row and "contribution_profit" in row:
            title = f"{row['channel']} leads contribution profit"
            detail = f"{row['currency']} {row['contribution_profit']:,.2f} after product costs, refunds and advertising. Ranked by the saved SQL."
        else:
            title, detail = "Query result is ready", f"{table.num_rows:,} output rows. Inspect the query and data before interpreting the result."
        evidence = {"step": step, "row_index": 0, "row": row}
    store.execute("INSERT INTO findings VALUES(?,?,?,?,?,?)", (store.uid(), run_id, artifact_id, title, detail, store.dumps(evidence)))


if __name__ == "__main__":
    run_pipeline(sys.argv[1])
