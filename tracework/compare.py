from decimal import Decimal, InvalidOperation
import pyarrow.parquet as pq
from . import store
from .pipelines import get_run


def compare_runs(workspace_id, left_id, right_id, key="channel", metric="contribution_profit"):
    left, right = get_run(workspace_id, left_id), get_run(workspace_id, right_id)
    if left["version"]["pipeline_id"] != right["version"]["pipeline_id"]:
        raise ValueError("Compare runs from the same pipeline")
    changes = []
    for name in sorted(set(left["inputs"]) | set(right["inputs"])):
        before, after = left["resolved_inputs"].get(name), right["resolved_inputs"].get(name)
        if (before or {}).get("id") != (after or {}).get("id"):
            changes.append(
                {
                    "source": name,
                    "before": before,
                    "after": after,
                    "content_changed": (before or {}).get("hash") != (after or {}).get("hash"),
                    "schema_changed": (before or {}).get("schema") != (after or {}).get("schema"),
                }
            )
    old_steps = {s["name"]: s for s in left["version"]["spec"]["steps"]}
    new_steps = {s["name"]: s for s in right["version"]["spec"]["steps"]}
    logic = [
        {"step": n, "before": old_steps.get(n), "after": new_steps.get(n)}
        for n in sorted(set(old_steps) | set(new_steps))
        if old_steps.get(n) != new_steps.get(n)
    ]
    result = {
        "left": left_id,
        "right": right_id,
        "input_changes": changes,
        "logic_changed": left["version"]["hash"] != right["version"]["hash"],
        "step_changes": logic,
        "parameters_changed": left["parameters"] != right["parameters"],
        "settings_changed": left["settings"] != right["settings"],
        "assumptions_before": left["version"]["spec"]["assumptions"],
        "assumptions_after": right["version"]["spec"]["assumptions"],
        "rows": [],
        "message": None,
        "key": key,
        "metric": metric,
    }
    if left["status"] != "successful" or right["status"] != "successful":
        result["message"] = (
            "Both runs must succeed for numeric comparison. Input and recipe changes remain inspectable."
        )
        return result

    def values(run):
        artifact = next(a for a in run["artifacts"] if a["step"] == run["version"]["spec"]["output"])
        data = store.one("SELECT path FROM datasets WHERE id=?", (artifact["dataset_id"],))
        table = pq.read_table(store.local_path(data["path"]))
        if key not in table.column_names or metric not in table.column_names:
            raise ValueError("Select a key and numeric metric present in both outputs")
        rows = table.to_pylist()
        if len({r[key] for r in rows}) != len(rows):
            raise ValueError("Comparison key must be unique; aggregate the output first")
        return {r[key]: r for r in rows}

    a, b = values(left), values(right)
    for name in sorted(set(a) | set(b), key=str):
        x, y = a.get(name), b.get(name)
        if x and y and x.get("currency") != y.get("currency"):
            raise ValueError("Cannot compare different currencies")
        try:
            before, after = (
                Decimal(str(x[metric])) if x else Decimal(0),
                Decimal(str(y[metric])) if y else Decimal(0),
            )
        except InvalidOperation as exc:
            raise ValueError("Comparison metric must contain numeric values") from exc
        result["rows"].append(
            {
                "key": name,
                "before": str(before),
                "after": str(after),
                "delta": str(after - before),
                "before_row": x,
                "after_row": y,
            }
        )
    return result
