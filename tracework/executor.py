"""Trusted executor child. It never receives provider credentials or executes Python from users."""

import os
import threading
import time
from decimal import Decimal
import resource
import sys
import pyarrow.parquet as pq
from . import store
from .engine import DuckDBBackend
from .ingest import profile_table
from .models import PipelineSpec, Settings
from .pipelines import resolve_inputs, version
from .sql import order_steps


def watch_parent():
    parent = os.getppid()

    def watch():
        while True:
            time.sleep(1)
            if os.getppid() != parent:
                os._exit(70)

    threading.Thread(target=watch, daemon=True).start()


def run_pipeline(run_id):
    run = store.one("SELECT * FROM runs WHERE id=?", (run_id,))
    settings = Settings.model_validate(run["settings"])
    resource.setrlimit(resource.RLIMIT_CPU, (settings.timeout_seconds + 5, settings.timeout_seconds + 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))
    spec = PipelineSpec.model_validate(version(run["workspace_id"], run["version_id"])["spec"])
    inputs = resolve_inputs(run["workspace_id"], run["inputs"])
    current, engine = None, None
    output = None
    try:
        for source in spec.sources:
            schema = {c["name"]: c["type"] for c in inputs[source.name]["schema"]}
            missing = set(source.columns) - set(schema)
            changed = {
                k: (source.columns[k], schema[k])
                for k in source.columns
                if k in schema and source.columns[k] != schema[k]
            }
            violations = [
                {"column": column, "expected": source.columns[column], "actual": schema.get(column)}
                for column in sorted(missing | set(changed))
            ]
            store.execute(
                "INSERT INTO checks VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    store.uid(),
                    run_id,
                    "__inputs__",
                    f"Source contract: {source.name}",
                    "blocking",
                    "failed" if violations else "passed",
                    len(violations),
                    "-- Schema contract checked before SQL execution",
                    store.dumps(violations),
                    None,
                ),
            )
            if missing or changed:
                raise ValueError(
                    f"Source contract failed for {source.name}: missing columns {sorted(missing)}; changed types {changed}. Map a compatible source version or explicitly revise the recipe."
                )
        engine = DuckDBBackend(inputs, settings)
        store.log(
            run_id, "Approved inputs materialized. External access disabled; engine configuration locked."
        )
        for step in order_steps(spec):
            current = step.name
            store.execute(
                "UPDATE step_executions SET status='running',started_at=? WHERE run_id=? AND name=?",
                (store.now(), run_id, current),
            )
            store.log(run_id, "Executing transformation", current)
            table = engine.query(step.sql, set(step.depends_on), run["parameters"])
            engine.materialize(current, table)
            artifact_id = save_artifact(run, current, table)
            failed = False
            for check in step.checks:
                try:
                    result = engine.query(check.sql, set(step.depends_on) | {current}, run["parameters"])
                except Exception as exc:
                    store.execute(
                        "INSERT INTO checks VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            store.uid(),
                            run_id,
                            current,
                            check.name,
                            check.severity,
                            "error",
                            None,
                            check.sql,
                            "[]",
                            store.safe_error(exc),
                        ),
                    )
                    raise ValueError(
                        f"Check {check.name} could not execute: {store.safe_error(exc)}"
                    ) from exc
                n = result.num_rows
                status = "passed" if n == 0 else "failed"
                store.execute(
                    "INSERT INTO checks VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        store.uid(),
                        run_id,
                        current,
                        check.name,
                        check.severity,
                        status,
                        n,
                        check.sql,
                        store.dumps(result.slice(0, 20).to_pylist()),
                        None,
                    ),
                )
                store.log(run_id, f"{check.severity}: {check.name} — {n} violating rows", current)
                failed |= bool(n and check.severity == "blocking")
            if failed:
                raise ValueError(
                    f"Blocking data-quality checks failed in {current}. Inspect violation samples; this attempt and its artifacts are preserved."
                )
            store.execute(
                "UPDATE step_executions SET status='successful',finished_at=? WHERE run_id=? AND name=?",
                (store.now(), run_id, current),
            )
            store.log(run_id, f"Materialized {table.num_rows:,} rows", current)
            if current == spec.output:
                output = (artifact_id, table, current)
        with store.transaction() as db:
            active = db.execute("SELECT status,cancel_requested FROM runs WHERE id=?", (run_id,)).fetchone()
            if active["status"] != "running" or active["cancel_requested"]:
                raise ValueError("Run cancelled or lease lost before completion")
            if output:
                create_finding(run_id, *output, db=db)
            db.execute("UPDATE runs SET status='successful',finished_at=? WHERE id=?", (store.now(), run_id))
        store.log(run_id, "Run completed. Findings link to the executed output.")
    except Exception as exc:
        error = store.safe_error(exc)
        if current:
            store.execute(
                "UPDATE step_executions SET status='failed',error=?,finished_at=? WHERE run_id=? AND name=?",
                (error, store.now(), run_id, current),
            )
        store.execute(
            "UPDATE step_executions SET status='skipped',finished_at=? WHERE run_id=? AND status='queued'",
            (store.now(), run_id),
        )
        cancelled = store.one("SELECT cancel_requested FROM runs WHERE id=?", (run_id,))["cancel_requested"]
        store.execute(
            "UPDATE runs SET status=?,error=?,finished_at=? WHERE id=? AND status='running'",
            ("cancelled" if cancelled else "failed", error, store.now(), run_id),
        )
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
        db.execute(
            "INSERT INTO datasets VALUES(?,?,?,?,?,?,?)",
            (
                did,
                run["workspace_id"],
                step,
                str(path.relative_to(store.root())),
                store.dumps(schema),
                store.dumps(profile),
                table.num_rows,
            ),
        )
        db.execute(
            "INSERT INTO artifacts VALUES(?,?,?,?,?)",
            (aid, run["id"], step, did, store.digest(path.read_bytes())),
        )
    return aid


def create_finding(run_id, artifact_id, table, step, db=None):
    if not table.num_rows:
        title, detail, evidence = (
            "The query returned no rows",
            "Review filters and source coverage.",
            {"step": step, "row_count": 0},
        )
    else:
        rows = table.to_pylist()
        row, row_index = rows[0], 0
        is_profit = all({"channel", "contribution_profit", "currency"} <= r.keys() for r in rows)
        if (
            is_profit
            and len({r["currency"] for r in rows}) == 1
            and all(isinstance(r["contribution_profit"], (int, float, Decimal)) for r in rows)
        ):
            row_index, row = max(enumerate(rows), key=lambda item: item[1]["contribution_profit"])
            title = f"{row['channel']} has the highest reported contribution profit"
            detail = f"{row['currency']} {row['contribution_profit']:,.2f}. Maximum verified across all {table.num_rows} output rows; see the saved SQL and assumptions for the calculation."
        else:
            title, detail = (
                "Query result is ready",
                f"{table.num_rows:,} output rows. Inspect the query and data before interpreting the result.",
            )
        evidence = {"step": step, "row_index": row_index, "row": row}
    (db.execute if db else store.execute)(
        "INSERT INTO findings VALUES(?,?,?,?,?,?)",
        (store.uid(), run_id, artifact_id, title, detail, store.dumps(evidence)),
    )


if __name__ == "__main__":
    watch_parent()
    run_pipeline(sys.argv[1])
