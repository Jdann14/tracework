import json
from fastapi.testclient import TestClient
from tracework import store
from tracework.api import app
from tracework.agent import AgentTools, OpenAIAdapter
from tracework.demo import load_batch, QUESTION
from tracework.worker import once


def test_api_demo_agent_approval_flow(workspace):
    with TestClient(app) as client:
        load_batch(workspace, 1)
        base = f"/api/workspaces/{workspace}"
        response = client.post(base + "/investigations", json={"question": QUESTION})
        assert response.status_code == 200
        once()
        detail = client.get(base).json()
        investigation = detail["investigations"][0]
        assert investigation["status"] == "proposed", investigation
        assert any(e["tool"] == "explore_sql" and "rows" in e["response"] for e in investigation["events"])
        vid = investigation["version_id"]
        inputs = {s["name"]: s["versions"][0]["id"] for s in detail["sources"]}
        request = {"version_id": vid, "inputs": inputs, "request_key": "api"}
        assert client.post(base + "/runs", json=request).status_code == 400
        assert client.post(base + f"/versions/{vid}/approve").status_code == 200
        queued = client.post(base + "/runs", json=request).json()
        once()
        run = client.get(base + f"/runs/{queued['id']}").json()
        assert run["status"] == "successful", run
        did = run["artifacts"][-1]["dataset_id"]
        assert client.get(base + f"/datasets/{did}?limit=1000").status_code == 422
        assert client.get(base + f"/datasets/{did}/download").status_code == 200
        assert (
            client.post(
                "/api/workspaces", json={"name": "Evil"}, headers={"origin": "https://evil.example"}
            ).status_code
            == 403
        )


def test_demo_missing_data_clarification(workspace):
    with TestClient(app) as client:
        job = client.post(f"/api/workspaces/{workspace}/investigations", json={"question": QUESTION}).json()
        once()
        stored = store.one("SELECT * FROM investigations WHERE id=?", (job["id"],))
        assert stored["status"] == "clarification"
        assert not store.all_rows("SELECT * FROM pipeline_versions")


def test_real_adapter_tool_roundtrip_and_no_secret_logs(workspace, monkeypatch):
    with TestClient(app) as client:
        job = client.post(
            f"/api/workspaces/{workspace}/investigations", json={"question": "Missing definition?"}
        ).json()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-private-credential")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    responses = [
        {
            "output": [
                {"type": "function_call", "name": "list_datasets", "arguments": "{}", "call_id": "call_1"}
            ]
        },
        {
            "output": [
                {
                    "type": "function_call",
                    "name": "request_clarification",
                    "arguments": json.dumps({"question": "Please provide cost data"}),
                    "call_id": "call_2",
                }
            ]
        },
    ]

    class FakeResponse:
        status_code = 200

        def json(self):
            return responses.pop(0)

    def post(self, url, **kwargs):
        assert url == "https://api.openai.com/v1/responses"
        assert kwargs["json"]["store"] is False
        if len(responses) == 1:
            assert kwargs["json"]["input"][-1]["type"] == "function_call_output"
        return FakeResponse()

    monkeypatch.setattr("httpx.Client.post", post)
    OpenAIAdapter().run(AgentTools(job))
    events = store.all_rows("SELECT * FROM tool_events")
    assert len(events) == 2
    assert "sk-test" not in json.dumps(events)


def test_multipart_upload_and_manifest(workspace):
    from tracework.models import RunRequest
    from tracework.pipelines import create_version, approve, enqueue
    from test_core import spec

    with TestClient(app) as client:
        base = f"/api/workspaces/{workspace}"
        upload = client.post(
            base + "/sources",
            data={"name": "orders"},
            files={"file": ("orders.csv", b"id,amount\n1,42\n", "text/csv")},
        )
        assert upload.status_code == 200
        ver = create_version(workspace, spec())
        approve(workspace, ver["id"])
        run = enqueue(
            workspace,
            RunRequest(version_id=ver["id"], inputs={"orders": upload.json()["id"]}, request_key="manifest"),
        )
        once()
        manifest = client.get(base + f"/runs/{run['id']}/manifest")
        assert manifest.status_code == 200
        assert "attachment" in manifest.headers["content-disposition"]
        assert manifest.json()["settings"]["engine_version"]
        assert manifest.json()["status"] == "successful"


def test_decimal_previews_preserve_cents(workspace):
    import io
    from decimal import Decimal
    import pyarrow as pa
    import pyarrow.parquet as pq

    buffer = io.BytesIO()
    value = Decimal("12345678901234.56")
    pq.write_table(pa.table({"balance": pa.array([value], type=pa.decimal128(18, 2))}), buffer)
    with TestClient(app) as client:
        base = f"/api/workspaces/{workspace}"
        upload = client.post(
            base + "/sources",
            data={"name": "balances"},
            files={"file": ("balances.parquet", buffer.getvalue(), "application/octet-stream")},
        )
        assert upload.status_code == 200
        dataset = client.get(base + "/datasets/" + upload.json()["dataset_id"]).json()
        assert dataset["data"][0]["balance"] == str(value)
