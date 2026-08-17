import sqlite3
import pytest
from tracework import store
from tracework.ingest import ingest
from tracework.models import PipelineSpec, RunRequest, Settings
from tracework.pipelines import create_version, approve, enqueue, get_run
from tracework.engine import DuckDBBackend
from tracework.worker import once, recover_stale
from tracework.sql import validate_sql


def spec(sql="SELECT id, sum(amount) AS total FROM orders GROUP BY id", checks=None):
    return PipelineSpec.model_validate({"title":"Totals", "assumptions":["USD amounts"], "sources":[{"name":"orders"}], "steps":[{"name":"totals", "title":"Order totals", "sql":sql,"depends_on":["orders"],"checks":checks or []}],"output":"totals"})


def queue(workspace, plan=None, data=b"id,amount\n1,10\n2,20\n", key="one"):
    src = ingest(workspace, "orders", "orders.csv", data)
    ver = create_version(workspace, plan or spec())
    approve(workspace, ver["id"])
    run = enqueue(workspace, RunRequest(version_id=ver["id"], inputs={"orders":src["id"]}, request_key=key))
    return run, src, ver


def test_immutable_input_versions(workspace):
    a = ingest(workspace,"orders","orders.csv",b"id,amount\n1,10\n")
    assert ingest(workspace,"orders","again.csv",b"id,amount\n1,10\n")["id"] == a["id"]
    b = ingest(workspace,"orders","orders.csv",b"id,amount\n1,11\n")
    assert a["id"] != b["id"]
    assert store.local_path(a["original_path"]).read_bytes() == b"id,amount\n1,10\n"
    with pytest.raises(sqlite3.IntegrityError):
        store.execute("UPDATE source_versions SET hash='x' WHERE id=?",(a["id"],))


def test_real_worker_and_idempotency(workspace):
    run, source, ver = queue(workspace)
    duplicate = enqueue(workspace, RunRequest(version_id=ver["id"],inputs={"orders":source["id"]},request_key="one"))
    assert duplicate["id"] == run["id"]
    with pytest.raises(ValueError,match="Request key"):
        enqueue(workspace, RunRequest(version_id=ver["id"],inputs={"orders":source["id"]},request_key="one",settings=Settings(threads=1)))
    once()
    result = get_run(workspace,run["id"])
    assert result["status"] == "successful", result["error"]
    assert result["artifacts"][0]["rows"] == 2
    assert result["findings"][0]["evidence"]["row_index"] == 0


def test_duplicates_block_with_preserved_artifact(workspace):
    check = {"name":"Unique orders", "sql":"SELECT id FROM totals GROUP BY id HAVING count(*)>1"}
    run,_,_ = queue(workspace,spec("SELECT * FROM orders",[check]),b"id,amount\n1,10\n1,10\n")
    once()
    result = get_run(workspace,run["id"])
    assert result["status"] == "failed"
    assert result["checks"][0]["violations"] == 1
    assert result["artifacts"] and not result["findings"]


@pytest.mark.parametrize("sql", ["SELECT * FROM read_csv('/etc/passwd')", "COPY orders TO '/tmp/stolen.csv'", "INSTALL httpfs", "SET enable_external_access=true", "ATTACH '/tmp/other.db' AS other", "SELECT * FROM other.orders", "DELETE FROM orders RETURNING *", "SELECT 1; SELECT 2", "SELECT * INTO output FROM orders"])
def test_sql_restrictions(sql):
    with pytest.raises(ValueError):
        validate_sql(sql,{"orders"})


def test_actual_engine_controls():
    engine = DuckDBBackend({}, Settings())
    for sql in ["SELECT * FROM read_csv('/etc/passwd')", "SELECT * FROM read_csv('https://example.com/a.csv')", "SET enable_external_access=true", "INSTALL httpfs", "COPY (SELECT 1) TO '/tmp/tracework-escape.csv'", "ATTACH '/tmp/no.db' AS escape"]:
        with pytest.raises(Exception):
            engine.con.execute(sql)
    assert engine.con.execute("SELECT current_setting('enable_external_access')").fetchone() == (False,)
    engine.close()


def test_cycle_and_workspace_isolation(workspace):
    invalid = spec()
    invalid.steps[0].depends_on = ["totals"]
    with pytest.raises(ValueError,match="Cyclic"):
        create_version(workspace,invalid)
    run, source, ver = queue(workspace)
    other = store.create_workspace("Other")["id"]
    with pytest.raises(LookupError):
        get_run(other,run["id"])
    v2 = create_version(other,spec())
    approve(other,v2["id"])
    with pytest.raises(ValueError,match="workspace"):
        enqueue(other,RunRequest(version_id=v2["id"],inputs={"orders":source["id"]},request_key="bad"))


def test_cancel_and_stale_worker(workspace):
    run,_,_ = queue(workspace)
    store.execute("UPDATE runs SET cancel_requested=1 WHERE id=?",(run["id"],))
    once()
    assert get_run(workspace,run["id"])["status"] == "cancelled"
    second,_,_ = queue(workspace,key="two")
    store.execute("UPDATE runs SET status='running',heartbeat='2000-01-01' WHERE id=?",(second["id"],))
    recover_stale()
    assert get_run(workspace,second["id"])["status"] == "failed"
