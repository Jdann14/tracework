# Verification record

Actual verification date: **2026-09-10**. Commit dates are the separately documented
history experiment. Host: macOS; Python 3.13.13, Node 25.9.0, DuckDB 1.5.5.

## Automated checks

- `uv run pytest -q`: **35 passed**, including real ingestion/execution subprocesses.
  Two upstream TestClient deprecation warnings remain (Starlette/httpx and AnyIO);
  neither is an application failure.
- Ruff lint and format checks: passed for application, tests and scripts.
- TypeScript compilation and Vite production build: passed.
- Prettier source formatting and `git diff --check`: passed.
- Dependency installation reported no npm audit vulnerabilities at verification.

Coverage includes immutable CSV/Parquet versions, hashes and originals; type
contracts; actual DuckDB I/O/extension/configuration restrictions; scoped SQL
validation; DAG cycle rejection; cross-workspace access rejection; duplicate IDs;
join multiplication; schema and currency failures; warning samples; check SQL
errors; result row limits; recursive-query wall timeout; in-flight and queued
cancellation; stale worker detection; unexpected child exit; run request
idempotency; parameter binding; exact decimal previews; manifest download;
pre-parser HTTP body limits; approval enforcement; missing-data clarification;
OpenAI function-call round trips with mocked transport; and independent result
comparison against Python/Decimal oracles.

## Public API walkthrough

`scripts/demo_walkthrough.py` ran against the actual FastAPI server and independent
worker. It created a separate persistent workspace and verified:

1. Seven-source baseline ingestion and audited demo investigation.
2. Approved v1 success, matching independent expected values.
3. Unchanged v1 fails against the changed spend schema.
4. V1 with compatible spend but new orders fails the duplicate-ID check.
5. Explicit proposed/approved v2 succeeds with the latest inputs.
6. Repeated v2 execution needs no model and produces the same expected values.
7. Comparison reports four changed source versions and changed recipe logic.

The app processes were stopped and restarted. Existing workspaces and versions
survived. A saved recovery recipe reran without an LLM, recorded DuckDB 1.5.5,
and exported its execution manifest. The built frontend and API responded with
HTTP 200. No fixture result was substituted into the UI.

## Browser verification

Using the running app's actual controls, verified:

- Create workspace; load seven-source demo; submit question and inspect proposal.
- Review source mappings, approve v1 and observe successful execution.
- Browse source rows and versions; load second batch; explicitly select latest
  versions and rerun the same v1 SQL.
- Read the schema failure; request repair; approve v2 and inspect recovered results.
- Compare baseline and recovery: Email 577→487 USD, Organic 527→527,
  Paid search 232→192, Paid social 167→51, Unattributed absent→116.
- Select dependency-graph nodes and inspect the corresponding checks.
- Inspect actual warning samples: duplicate O001, unmatched refund O999,
  late-arriving refunds and orders O008/O020 missing attribution.
- Use the multi-file chooser to upload orders/refunds; completed upload/profile
  status is visible, and identical bytes reuse their existing source versions.
- Navigate from the Organic finding to its output row; reload and recover saved
  workspace, recipe and run state.
- Inspect rendered desktop layout and narrow layout. At the observed 375px mobile
  width, document scroll width equals client width; wide tables/graphs scroll in
  their own containers. No browser console errors after final reload.

Browser checks used the desktop browser automation surface. There is no claimed
Playwright test suite or unexecuted placeholder test command in this repository.

## Git audit

The final sequence has 22 coherent commits, with identical author and committer
dates, strictly increasing throughout the new history:

| Days before 2026-09-10 | Experimental day | Commits |
| ---: | --- | ---: |
| 28 | August 13 | 3 |
| 24 | August 17 | 5 |
| 23 | August 18 | 1 |
| 17 | August 24 | 7 |
| 9 | September 1 | 2 |
| 3 | September 7 | 4 |

Commits were made as features were implemented, not assembled from the finished
tree. The configured Git identity was inherited, no prior repository was modified,
and there is no remote push. `.tracework`, credentials, dependencies and build
outputs are ignored. The final Git working tree is clean.

## Not verified or not implemented

A live OpenAI call was not made because no API credential was supplied. The real
provider adapter and payload/tool handling were tested with mocked HTTP responses.
No claim is made of Windows support, hostile multi-tenant security, an OS sandbox,
a hard total-RSS cap, incremental data processing, scheduling or causal explanation
of result deltas. See SECURITY.md and ARCHITECTURE.md for exact boundaries.
