"""AST validation is defense in depth; DuckDB configuration is the I/O boundary."""
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope


def validate_sql(sql, available):
    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"SQL parse error: {exc}") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise ValueError("Exactly one SELECT or WITH query is required")
    tree = statements[0]
    # Reject DDL/DML anywhere, including CTEs and SELECT INTO.
    for node in tree.walk():
        if isinstance(node, (exp.DDL, exp.DML, exp.Command, exp.Into, exp.Lock)):
            raise ValueError("Only relational queries are allowed")
    refs = set()
    for scope in traverse_scope(tree):
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                if not isinstance(source.this, exp.Identifier) or source.db or source.catalog:
                    raise ValueError("Table functions and qualified catalogs are not allowed")
                refs.add(source.name)
    unknown = refs - set(available)
    if unknown:
        raise ValueError("Query references undeclared inputs: " + ", ".join(sorted(unknown)))
    return tree.sql(dialect="duckdb"), refs


def order_steps(spec):
    names = [s.name for s in spec.steps]
    sources = [s.name for s in spec.sources]
    if len(set(names + sources)) != len(names + sources):
        raise ValueError("Source and step names must be distinct")
    if spec.output not in names:
        raise ValueError("Output must name a pipeline step")
    pending = list(spec.steps)
    available = set(sources)
    ordered = []
    while pending:
        ready = [s for s in pending if set(s.depends_on) <= available]
        if not ready:
            raise ValueError("Cyclic pipeline or unknown dependency")
        for step in ready:
            validate_sql(step.sql, step.depends_on)
            for check in step.checks:
                validate_sql(check.sql, set(step.depends_on) | {step.name})
            ordered.append(step)
            available.add(step.name)
            pending.remove(step)
    return ordered
