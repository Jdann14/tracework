# Implementation plan

Execution began 2026-09-10. The enclosing Documents directory had no repository or
applicable instructions. Existing projects are preserved; this new repository is
Tracework. Git identity is inherited. New commits use increasing experimental
August 13, 17, 18, 24 and September 1, 7 timestamps (28/24/23/17/9/3 days earlier).
These dates are an explicit history experiment, not actual implementation dates.

1. Establish Python/React tooling and explicit durable domain models.
2. Ingest immutable CSV/Parquet versions; inspect schemas, profiles and samples.
3. Validate versioned SQL DAGs and source contracts; queue approved runs.
4. Execute in worker-owned processes with engine controls, checks and artifacts.
5. Generate two commerce batches and independently calculated expected results.
6. Add bounded investigation tools, no-key demo and real OpenAI adapter.
7. Connect conversation, source/pipeline browser, inspector and comparisons.
8. Exercise complete rerun/failure/revision flow, inspect UI and document limits.

Each completed feature is committed before starting the next coherent slice.
No external hosting: this is explicitly a local, single-user Python application.

## Completion

All eight planned slices are implemented and verified. The React interface uses
an actual dependency graph, source and evidence previews, approval/mapping dialogs,
version creation, worker progress, checks/logs and output comparisons. The final
verification record lists 35 passing tests, the public API walkthrough, browser
checks, restart/replay validation and explicit remaining limits. The real provider
requires user-supplied credentials; the no-key adapter uses the same real engine.
