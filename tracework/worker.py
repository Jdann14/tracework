"""One local supervisor. SQLite claims, heartbeats and child death make failures visible."""

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from . import store
from .ingest import child_env


def finish_run(run_id, status, message):
    with store.transaction() as db:
        db.execute(
            "UPDATE runs SET status=?,error=?,finished_at=? WHERE id=? AND status IN ('running','queued')",
            (status, message, store.now(), run_id),
        )
        db.execute(
            "UPDATE step_executions SET status=?,error=?,finished_at=? WHERE run_id=? AND status='running'",
            (status, message, store.now(), run_id),
        )
        db.execute(
            "UPDATE step_executions SET status=?,finished_at=? WHERE run_id=? AND status='queued'",
            ("cancelled" if status == "cancelled" else "skipped", store.now(), run_id),
        )
    store.log(run_id, message)


def recover_stale(seconds=15):
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    for run in store.all_rows("SELECT id FROM runs WHERE status='running' AND heartbeat<?", (cutoff,)):
        finish_run(
            run["id"],
            "failed",
            "Worker heartbeat expired. Interrupted attempt preserved; queue a new run to recover.",
        )
    store.execute(
        "UPDATE investigations SET status='failed',error='Worker heartbeat expired; submit a new investigation' WHERE status='running' AND heartbeat<?",
        (cutoff,),
    )


def claim(table):
    if table not in ("runs", "investigations"):
        raise ValueError("Unknown queue")
    with store.transaction() as db:
        row = db.execute(
            f"SELECT * FROM {table} WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            return None
        db.execute(f"UPDATE {table} SET status='running',heartbeat=? WHERE id=?", (store.now(), row["id"]))
        if table == "runs":
            db.execute("UPDATE runs SET started_at=? WHERE id=?", (store.now(), row["id"]))
        return store.decode(row)


def tick():
    store.execute(
        "INSERT INTO worker_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat",
        (store.now(),),
    )


def supervise(job, table="runs"):
    is_run = table == "runs"
    env = child_env()
    if not is_run:
        # Credentials are available only in agent children, never SQL/ingestion children.
        env.update({k: v for k, v in os.environ.items() if k in ("OPENAI_API_KEY", "OPENAI_MODEL")})
    module = "tracework.executor" if is_run else "tracework.agent"
    timeout = job["settings"]["timeout_seconds"] if is_run else 150
    process = subprocess.Popen(
        [sys.executable, "-m", module, job["id"]],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    started = time.monotonic()
    reason, status = None, "failed"
    try:
        while process.poll() is None:
            tick()
            row = store.one(f"SELECT * FROM {table} WHERE id=?", (job["id"],))
            if is_run and row["cancel_requested"]:
                reason, status = "Cancelled by user; partial artifacts are preserved.", "cancelled"
                break
            if row["status"] != "running":
                # A recovered stale job must never continue writing as a successful run.
                if row["status"] not in ("successful", "completed", "clarification", "proposed"):
                    reason = "Job is no longer active"
                    break
            if time.monotonic() - started > timeout:
                reason = f"Execution exceeded {timeout} seconds; child process terminated."
                break
            store.execute(f"UPDATE {table} SET heartbeat=? WHERE id=?", (store.now(), job["id"]))
            time.sleep(0.15)
    except BaseException:
        reason = "Worker stopped during execution; interrupted attempt preserved."
        raise
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        row = store.one(f"SELECT status FROM {table} WHERE id=?", (job["id"],))
        if reason or row["status"] == "running":
            reason = reason or f"Execution process exited unexpectedly (code {process.returncode})."
            if is_run:
                finish_run(job["id"], status, reason)
            else:
                store.execute(
                    "UPDATE investigations SET status='failed',error=? WHERE id=?", (reason, job["id"])
                )


def once():
    tick()
    recover_stale()
    for table in ("runs", "investigations"):
        job = claim(table)
        if job:
            supervise(job, table)
            return True
    return False


def main():
    import fcntl

    def shutdown(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)

    store.init()
    lock = (store.root() / "worker.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another Tracework worker is already active")
    print("Tracework worker ready", flush=True)
    try:
        while True:
            if not once():
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("Tracework worker stopped", flush=True)


if __name__ == "__main__":
    main()
