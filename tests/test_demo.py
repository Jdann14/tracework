from decimal import Decimal
from tracework.demo import load_batch, commerce_spec, expected, encode_csv, batches
from tracework.ingest import ingest
from tracework.models import RunRequest
from tracework.pipelines import create_version, approve, enqueue, get_run
from tracework.worker import once


def execute(workspace, vid, inputs, key):
    run = enqueue(workspace, RunRequest(version_id=vid, inputs=inputs, request_key=key))
    once()
    return get_run(workspace, run["id"])


def result(run):
    artifact = next(a for a in run["artifacts"] if a["step"] == "channel_profit")
    return {r["channel"]: Decimal(r["contribution_profit"]) for r in artifact["profile"]["sample"]}


def test_two_batches_failure_revision_and_oracle(workspace):
    first = load_batch(workspace, 1)
    v1 = create_version(workspace, commerce_spec(workspace))
    approve(workspace, v1["id"])
    r1 = execute(workspace, v1["id"], first, "first")
    assert r1["status"] == "successful", r1["error"]
    assert result(r1) == expected(1)
    second = load_batch(workspace, 2)
    failed = execute(workspace, v1["id"], second, "second")
    assert failed["status"] == "failed" and "contract" in failed["error"]
    # Compatible ad spend mapping gets past schema validation and exposes duplicates.
    mixed = second | {"ad_spend": first["ad_spend"]}
    duplicate = execute(workspace, v1["id"], mixed, "duplicate")
    assert duplicate["status"] == "failed"
    assert any(c["name"] == "Unique order IDs" and c["status"] == "failed" for c in duplicate["checks"])
    v2 = create_version(workspace, commerce_spec(workspace, True), v1["id"])
    approve(workspace, v2["id"])
    fixed = execute(workspace, v2["id"], second, "recovery")
    assert fixed["status"] == "successful", fixed["error"]
    assert result(fixed) == expected(2)
    assert fixed["version"]["parent_id"] == v1["id"]
    warnings = [c for c in fixed["checks"] if c["status"] == "failed" and c["severity"] == "warning"]
    assert {c["name"] for c in warnings} >= {
        "Missing attribution",
        "Refunds with no matching order",
        "Duplicate source orders",
        "Late-arriving refunds",
    }
    repeated = execute(workspace, v2["id"], second, "same-inputs-again")
    assert result(repeated) == result(fixed)


def test_cost_join_multiplication_blocks(workspace):
    inputs = load_batch(workspace, 1)
    rows = batches()["product_costs"]
    rows.append(rows[0])
    inputs["product_costs"] = ingest(workspace, "product_costs", "costs.csv", encode_csv(rows))["id"]
    ver = create_version(workspace, commerce_spec(workspace))
    approve(workspace, ver["id"])
    run = execute(workspace, ver["id"], inputs, "multiply")
    assert run["status"] == "failed"
    assert any(c["name"] == "Join preserves item grain" and c["violations"] for c in run["checks"])
