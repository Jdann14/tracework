"""Reproduce the complete story through the public API and real worker.

Run the app first. This script creates its own workspace; it does not erase data.
"""

import time
import httpx
from tracework.demo import QUESTION, expected
from decimal import Decimal


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000/api", timeout=60) as client:

        def request(method, path, body=None):
            response = client.request(method, path, json=body)
            response.raise_for_status()
            return response.json()

        health = request("GET", "/health")
        if not health["worker_online"]:
            raise SystemExit("Start the Tracework worker before running this walkthrough")
        workspace = request("POST", "/workspaces", {"name": "Commerce walkthrough"})
        base = "/workspaces/" + workspace["id"]

        def wait(fetch, statuses, timeout=60):
            started = time.monotonic()
            while time.monotonic() - started < timeout:
                value = fetch()
                if value["status"] in statuses:
                    return value
                time.sleep(0.25)
            raise TimeoutError("Worker did not finish within the walkthrough deadline")

        def investigate(question, **kwargs):
            job = request(
                "POST", base + "/investigations", {"question": question, "provider": "demo", **kwargs}
            )
            result = wait(
                lambda: next(i for i in request("GET", base)["investigations"] if i["id"] == job["id"]),
                {"proposed", "clarification", "failed"},
            )
            assert result["status"] == "proposed", result
            return result["version_id"]

        def run(vid, inputs, key):
            job = request("POST", base + "/runs", {"version_id": vid, "inputs": inputs, "request_key": key})
            return wait(
                lambda: request("GET", base + "/runs/" + job["id"]), {"successful", "failed", "cancelled"}
            )

        first = request("POST", base + "/demo/1")["inputs"]
        v1 = investigate(QUESTION)
        request("POST", base + f"/versions/{v1}/approve")
        baseline = run(v1, first, "baseline")
        assert baseline["status"] == "successful", baseline
        second = request("POST", base + "/demo/2")["inputs"]
        drift = run(v1, second, "schema-drift")
        assert drift["status"] == "failed" and "Source contract" in drift["error"]
        duplicate = run(v1, second | {"ad_spend": first["ad_spend"]}, "duplicate-records")
        assert duplicate["status"] == "failed" and any(
            c["name"] == "Unique order IDs" and c["status"] == "failed" for c in duplicate["checks"]
        )
        v2 = investigate(
            "Repair the recipe: accept spend_cents and remove exact duplicate order rows.",
            base_version_id=v1,
            failed_run_id=drift["id"],
        )
        request("POST", base + f"/versions/{v2}/approve")
        recovery = run(v2, second, "recovery")
        assert recovery["status"] == "successful", recovery
        replay = run(v2, second, "repeat-without-llm")
        assert replay["status"] == "successful", replay
        for execution, batch in ((baseline, 1), (recovery, 2), (replay, 2)):
            artifact = next(a for a in execution["artifacts"] if a["step"] == "channel_profit")
            actual = {r["channel"]: Decimal(r["contribution_profit"]) for r in artifact["profile"]["sample"]}
            assert actual == expected(batch), (actual, expected(batch))
        comparison = request("GET", base + f"/compare?left={baseline['id']}&right={recovery['id']}")
        assert comparison["logic_changed"] and len(comparison["input_changes"]) == 4
        print(f"Workspace: {workspace['name']} ({workspace['id']})")
        print(
            "PASS: baseline, schema failure, duplicate failure, explicit revision, no-LLM replay, independent expected results, comparison"
        )
        for row in comparison["rows"]:
            print(f"  {row['key']:15} {row['before']:>8} → {row['after']:>8} USD  delta {row['delta']}")
        print("Open http://127.0.0.1:4318 and select Commerce walkthrough to inspect the persisted work.")


if __name__ == "__main__":
    main()
