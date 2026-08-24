"""Execution interface: SQL today; other engines can implement this protocol later."""

from typing import Protocol
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import sqlglot
from sqlglot import exp
from .ingest import identifier
from .models import Settings
from .sql import validate_sql
from . import store


class ExecutionBackend(Protocol):
    def query(self, sql: str, allowed: set[str], parameters: dict) -> pa.Table: ...
    def materialize(self, name: str, table: pa.Table) -> None: ...
    def close(self) -> None: ...


class DuckDBBackend:
    def __init__(self, inputs, settings: Settings):
        self.settings = settings
        self.con = duckdb.connect(
            config={
                "memory_limit": f"{settings.memory_mb}MB",
                "threads": settings.threads,
                "autoinstall_known_extensions": False,
                "autoload_known_extensions": False,
                "allow_unsigned_extensions": False,
                "allow_community_extensions": False,
                "temp_directory": "",
                "max_temp_directory_size": "0B",
            }
        )
        # Trusted bootstrap only. Materialize approved inputs into memory before locking I/O.
        for name, source in inputs.items():
            table = pq.read_table(store.local_path(source["path"]))
            self.materialize(name, table)
        self.con.execute("SET enable_external_access=false")
        self.con.execute("SET disabled_filesystems='LocalFileSystem,HTTPFileSystem' ")
        self.con.execute("SET lock_configuration=true")

    def materialize(self, name, table):
        self.con.register("_tracework_arrow", table)
        self.con.execute(f"CREATE TABLE {identifier(name)} AS SELECT * FROM _tracework_arrow")
        self.con.unregister("_tracework_arrow")

    def query(self, sql, allowed, parameters):
        checked, _ = validate_sql(sql, allowed)
        tree = sqlglot.parse_one(checked, read="duckdb")
        used = {p.name for p in tree.find_all(exp.Placeholder)}
        values = {k: v for k, v in parameters.items() if k in used}
        result = self.con.execute(checked, values or None).fetch_record_batch(4096)
        batches, rows = [], 0
        for batch in result:
            rows += batch.num_rows
            if rows > self.settings.max_output_rows:
                raise ValueError(
                    f"Query exceeds {self.settings.max_output_rows:,} output rows; aggregate or filter it"
                )
            batches.append(batch)
        return pa.Table.from_batches(batches, schema=result.schema)

    def close(self):
        self.con.close()
