# Execution boundary and local limits

Tracework is intended for one trusted OS user on macOS or Linux. Bind it to
loopback. It has no authentication, tenant boundary, TLS termination or internet
service hardening. Do not expose the API or Vite server publicly.

## Actual controls

| Boundary | Implemented control |
| --- | --- |
| HTTP uploads | Declared and streamed request bytes capped at 50 MiB + 128 KiB multipart allowance before parsing; retained file bytes capped at 50 MiB |
| Ingestion | Separate credential-free process; one app-selected original; 35-second parent deadline, 25-second CPU limit, 256 MiB per-file output limit |
| Input sizing | 500,000 rows / 100 columns per upload; at most 1,000,000 mapped rows per run; Parquet expanded-size metadata capped at 256 MiB |
| Names and paths | SQL-safe logical names, generated UUID paths, resolved-path containment, workspace ownership checks |
| Execution SQL | AST query validation and declared relation checks, including nested scopes; rejects cycles and multiple statements |
| Engine I/O | Mapped inputs materialized first; `enable_external_access=false`; LocalFileSystem and HTTPFileSystem disabled; empty temp directory; zero spill budget |
| Extensions | Auto-install, auto-load, unsigned and community extensions disabled; configuration locked before untrusted queries |
| Resources | 45-second default wall deadline (1–120 configurable); CPU deadline + 5 seconds; 512 MiB default DuckDB memory (64–1024); 1–4 threads; 256 MiB per-file process limit |
| Output | 100,000 default rows per step/check (1–1,000,000); incremental Arrow batches stop excessive results; partial output remains inspectable |
| Preview | API at most 100 rows/page; profile 30 rows; agent samples at most 20 rows; exploration at most 100 rows / 10 seconds; long strings truncated at 2,000 characters and nested lists at 50 items in previews |
| Worker | Exclusive POSIX worker lock, transactional claim, heartbeats, child process-group kill, parent-death watch, explicit failure recovery |
| Credentials | Environment-only provider credentials; SQL/ingestion/exploration subprocess environment allowlist excludes keys; secret values redacted from agent audit/errors; provider HTTP error bodies omitted |
| Browser | Trusted loopback Host names; explicit localhost Origin allowlist; no cross-origin access enabled; typed data rendered through React text escaping |
| Originals | Original bytes retained, content hashes recorded, read-only file mode, no overwrite or deletion API |

Tests exercise the actual DuckDB connection's file reads, HTTP reads, extension
installation, configuration changes, COPY and ATTACH, in addition to AST rejection.
The restrictions are not a keyword blacklist.

## Precise limitations

This is **not an OS sandbox**. The trusted Python process runs as the local OS
user and can read application metadata and write its own artifacts. DuckDB's
configuration restricts SQL-driven I/O; SQLGlot is additional validation, not a
security boundary for native engine defects. A vulnerability in DuckDB, PyArrow,
CSV/Parquet parsing or another native library could escape application controls.
There are no seccomp rules, network namespace, container, VM, unprivileged UID or
filesystem jail. Host-level network denial is not installed.

DuckDB's memory setting is not a hard process RSS cap. Arrow input/output tables,
profiling connections and native-library overhead can use additional memory.
POSIX CPU and file-size limits and the supervisor wall timeout are enforced;
macOS does not provide a portable reliable hard process-memory cap here. Malformed
compressed input metadata may not reflect actual decompression memory. Keep data
small and use an OS/container boundary before accepting adversarial remote users.

Original file permissions and hashes protect against accidental application edits,
not a malicious OS owner. Data and metadata are not encrypted. Downloads contain
the uploaded/computed data. CSV exports quote CSV fields but do not rewrite values
that spreadsheet applications might interpret as formulas; inspect untrusted
text before opening it in a formula-enabled spreadsheet.

The OpenAI adapter intentionally sends the question, schemas, profiles, bounded
samples, exploratory results and recent investigation context to OpenAI when the
user chooses that provider. No-key demo mode does not make those requests. The
model can misunderstand data or propose poor assumptions; user approval and checks
are required, and do not guarantee analytical correctness. Real API access was
not exercised without credentials; protocol behavior is covered by mocked HTTP
tests against the real adapter.

Dependencies are locked. Use the lockfiles and rerun the execution-restriction
tests after upgrading the engine or parsers. Production hardening, multi-user
authorization and larger data processing are future work, not implemented features.
