# Tracework

**Ask a question. Keep the investigation, SQL, checks and evidence. Run it again.**

Tracework is a working, local AI data workspace: FastAPI, DuckDB, SQLite, immutable
files, a separate execution worker, and a React/TypeScript interface. Its defining
demo is the second run: new commerce data breaks the saved recipe, an explicit
revision repairs it, and a comparison explains which inputs and SQL changed.

## Run locally

Requires macOS or Linux, Node.js 22+, npm and [uv](https://docs.astral.sh/uv/).
Python 3.13 is selected by the setup command. No Docker or external database needed.

```sh
cd /path/to/tracework
uv sync --python 3.13 --locked
npm ci --prefix web
uv run python scripts/dev.py
```

Open **http://127.0.0.1:4318**. API documentation: **http://127.0.0.1:8000/docs**.
The command starts API, worker and Vite together; Ctrl+C stops them. Keep ports
8000 and 4318 free. Restart after changing environment variables or worker code.
The interface displays whether the worker is connected. If it is offline, queued
work persists until it returns.

Default mode is **Demo · deterministic**, clearly labeled in the interface. It
needs no API key and makes no model requests. Dependencies and fonts are local
after setup. Demo results come from real DuckDB execution, not hardcoded UI rows.

Optional `.env` settings are loaded by `scripts/dev.py`. Storage defaults to the
repository's gitignored `.tracework/`. Set `TRACEWORK_DATA_DIR` to an absolute path
to keep it elsewhere. Sources, investigations, pipelines, approvals, runs and
artifacts survive restarts. Back up the whole directory with services stopped.

## The five-minute demo

1. Create **Acme Commerce**. Click **Load demo batch 1** in the investigation area.
2. Send the suggested contribution-profit question. Expand recorded tool calls to
   inspect source profiles, sample rows and the actual exploratory SQL result.
3. Review the proposed recipe, its dependency graph, SQL, checks and assumptions.
   Click **Review & run**. Confirm the explicit source mappings and approve v1.
4. Inspect the successful run. **Email: USD 577.00** is the leading result. Click
   the finding to open its supporting data, or select a step to inspect SQL,
   checks, intermediate output and execution logs.
5. Open **Sources → Load demo batch 2**. Then **Run pipeline → Use latest versions
   → Queue run with these inputs**. No model is called and SQL stays at v1.
6. The run fails because `ad_spend.amount_cents` became `spend_cents`. Inspect the
   failed source contract. To expose the second issue, queue v1 again with all
   latest sources **except ad_spend v1**: duplicate order IDs now block the run.
7. From the failed run, click **Propose a repair**, then send the prefilled request
   to accept `spend_cents` and remove exact duplicate orders. Review and approve
   **v2**, mapping all latest versions. V1 and its failed attempts remain intact.
8. The recovery succeeds with warnings for duplicates, missing attribution,
   unmatched refunds and late refunds. **Organic: USD 527.00** now leads.
9. Open **Compare**, choose the original success and recovered success, and click
   **Compare runs**. Four sources changed; two transformation definitions changed.
   Inspect schema/hash differences and before/after SQL. Rerun v2 again to verify
   the same output without another model call.
10. Use **Edit recipe** or **Request change** to create another version. Reopening
    the workspace retains previous versions, investigation history and run evidence.

A reproducible API walkthrough performs the same persisted flow and asserts both
results against an independent Python/Decimal calculation:

```sh
# Leave the app running in another terminal.
uv run python scripts/demo_walkthrough.py
```

It creates a new **Commerce walkthrough** workspace without altering existing
workspaces. The fixtures are checked into `demo/batch1/` and `demo/batch2/`;
regenerate them with `uv run python -m tracework.demo`.

| Channel | Batch 1 profit (USD) | Batch 2, recovered (USD) |
| --- | ---: | ---: |
| Email | 577.00 | 487.00 |
| Organic | 527.00 | 527.00 |
| Paid search | 232.00 | 192.00 |
| Paid social | 167.00 | 51.00 |
| Affiliates | -40.00 | -40.00 |
| Unattributed | absent | 116.00 |

Profit is item revenue minus product costs, matched refunds and advertising.
Amounts originate in integer USD cents; output uses decimal USD. Attribution uses
the one supplied customer acquisition channel. Refunds reduce the original
channel, including late arrivals; unmatched refunds warn and are excluded. Missing
attribution stays Unattributed. Costs are not reversed on refunds. Tax, shipping,
fees, fulfillment and overhead are absent and excluded. Inputs are full snapshots,
not incremental feeds. These assumptions are stored in every demo recipe.

## Use your own data and a real LLM

Upload one or several CSV/Parquet files with **Add data**. File names become logical
source names for a multi-file upload; a single upload can name its source explicitly.
Reusing a logical name adds an immutable version. Sources expose typed schema,
missing/distinct counts, numeric statistics, samples, pagination and Parquet export.
Column names must be SQL identifiers; unsupported names get a clear ingestion error.

Copy `.env.example` to `.env` and set:

```dotenv
TRACEWORK_PROVIDER=openai
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-tool-capable-model-id
```

Restart the app and choose **OpenAI · real provider**. Use a model you have access
to that supports Responses API function calling. The provider uses the fixed
`https://api.openai.com/v1/responses` endpoint, `store=false`, and recorded tool
calls. Credentials stay in the environment; do not place them in questions or
source files. This mode sends questions, schemas, samples and exploratory results
to OpenAI. See the [official function-calling guide](https://developers.openai.com/api/docs/guides/function-calling).

The model investigates through bounded tools and proposes a validated recipe.
Missing definitions can produce a clarification; reply in the conversation.
Review its SQL and assumptions before approval. No LLM is required to rerun an
approved pipeline. An agent repair is a new proposed version, never a silent edit;
repair proposals are bounded to two per failed run.

For custom changes in demo mode, edit the structured recipe directly. The fixed
demo adapter only knows its commerce analysis and standard recovery, and says so
when asked for other work.

## Tests and production build

```sh
uv run pytest -q
uv run ruff check tracework tests scripts
uv run ruff format --check tracework tests scripts
npm run build --prefix web
```

The tests cover immutable input versions, CSV and Parquet ingestion, workspace
isolation, SQL AST and actual engine restrictions, cyclic dependencies, joins that
multiply rows, blocking checks and warnings, schema/type drift, named parameters,
row/time limits, cancellation, stale heartbeats, unexpected child exits,
idempotent requests, audited agents, approval, evidence and comparisons. Expected
commerce results are calculated separately from SQL. Provider HTTP tests mock the
transport while exercising the actual OpenAI adapter; a live model call was not
performed without credentials.

Browser QA exercised workspace creation, batch upload, investigation, approval,
execution, source previews, the failed second run, explicit recovery, comparisons,
step checks, evidence links and responsive rendering. [Verification notes](docs/VERIFICATION.md).

For a built frontend served by FastAPI:

```sh
npm run build --prefix web
# In separate terminals; export environment variables yourself for this mode.
uv run uvicorn tracework.api:app --host 127.0.0.1 --port 8000
uv run python -m tracework.worker
```

Then open **http://127.0.0.1:8000**. The API serves `web/dist` when present at startup.

## Architecture, guarantees and boundaries

[Architecture diagram and decisions](docs/ARCHITECTURE.md) ·
[Execution controls and precise limitations](docs/SECURITY.md).

This is a local single-user product, not a multi-user hosted service. Only SQL is
implemented behind the execution interface. It has no authentication, scheduling,
cloud storage, incremental execution or Python transformation backend. Manual
revision edits structured JSON; graph nodes are inspectable but not draggable.
Comparison is descriptive and does not claim causal attribution of each delta.

DuckDB I/O and extension controls, locked settings, AST validation and bounded
processes are implemented and tested. They are **not an OS sandbox**. Native
engine/parser vulnerabilities and memory outside DuckDB's own allocator remain
outside that boundary. Read the security document before changing deployment scope.

## Git-history experiment

Actual implementation began **2026-09-10**. New commits use deliberately irregular,
increasing author and committer timestamps on August 13, 17, 18, 24 and September 1,
7 (28, 24, 23, 17, 9 and 3 days earlier). These are experimental dates, not an
assertion that implementation occurred then. The configured identity was preserved;
no pre-existing repository history was changed and no remote push was performed.
