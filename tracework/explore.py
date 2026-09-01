"""Short-lived exploratory SQL child, using the same execution boundary as runs."""

import json
import resource
import sys
from pathlib import Path
from . import store
from .engine import DuckDBBackend
from .ingest import preview_rows
from .models import Settings
from .pipelines import resolve_inputs


def main(path):
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    request = json.loads(path.read_text())
    inputs = resolve_inputs(request["workspace_id"], request["inputs"])
    engine = DuckDBBackend(inputs, Settings(timeout_seconds=8, max_output_rows=100))
    try:
        table = engine.query(request["sql"], set(inputs), {})
        output = {
            "rows": preview_rows(table, 100),
            "columns": table.column_names,
            "input_versions": request["inputs"],
            "sql": request["sql"],
        }
        path.with_suffix(".result.json").write_text(store.dumps(output))
    finally:
        engine.close()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
