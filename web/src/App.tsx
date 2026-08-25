import { useCallback, useEffect, useState, useRef } from "react";
import {
  ArrowUp,
  ArrowUpRight,
  ArrowRight,
  Plus,
  Play,
  Upload,
  GitBranch,
  Database,
  MessageSquare,
  Layers,
  ChevronDown,
  Check,
  RotateCcw,
  FlaskConical,
  PanelRight,
  Command,
  FileCode2,
  Activity,
  Loader2,
  Settings2,
  Sparkles,
} from "lucide-react";
import {
  api,
  post,
  short,
  time,
  type WorkspaceData,
  type Version,
  type RunDetail,
  type Investigation,
  type SourceVersion,
} from "./api";
import { Status, Empty, Modal, DataPreview } from "./components";
import { RunInspector, CompareView } from "./inspectors";
const QUESTION =
  "Which marketing channels generate the most contribution profit after product costs, refunds, and advertising spend?";
const EMPTY: WorkspaceData = {
  sources: [],
  pipelines: [],
  runs: [],
  investigations: [],
};

export default function App() {
  const [workspaces, setWorkspaces] = useState<{ id: string; name: string }[]>(
      [],
    ),
    [wid, setWid] = useState(localStorage.getItem("tracework.workspace") || "");
  const [data, setData] = useState<WorkspaceData>(EMPTY),
    [health, setHealth] = useState<{
      worker_online: boolean;
      openai_configured: boolean;
      provider: string;
    } | null>(null);
  const [vid, setVid] = useState(""),
    [rid, setRid] = useState(""),
    [run, setRun] = useState<RunDetail | null>(null),
    [selectedStep, setSelectedStep] = useState("");
  const [view, setView] = useState("recipe"),
    [dataset, setDataset] = useState(""),
    [evidence, setEvidence] = useState(-1),
    [provider, setProvider] = useState("demo");
  const [question, setQuestion] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(""),
    [modal, setModal] = useState("");
  const [newName, setNewName] = useState("Commerce analysis"),
    [inputs, setInputs] = useState<Record<string, string>>({}),
    [draft, setDraft] = useState(""),
    [sourceName, setSourceName] = useState(""),
    [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [parameters, setParameters] = useState("{}"),
    [timeout, setTimeoutSeconds] = useState(45),
    [repair, setRepair] = useState(false);
  const lastProposal = useRef<string | null>(null);
  const versions = data.pipelines.flatMap((p) => p.versions),
    version = versions.find((v) => v.id === vid);
  const base = `/workspaces/${wid}`;
  const refresh = useCallback(async () => {
    if (!wid) return;
    const next = await api<WorkspaceData>(`/workspaces/${wid}`);
    setData(next);
    setRid((prev) => prev || next.runs[0]?.id || "");
    const proposed = [...next.investigations]
      .reverse()
      .find((i) => i.version_id);
    if (proposed?.version_id && proposed.version_id !== lastProposal.current) {
      if (lastProposal.current !== null) {
        setVid(proposed.version_id);
        setView("recipe");
      }
      lastProposal.current = proposed.version_id;
    } else if (lastProposal.current === null) {
      lastProposal.current = "";
    }
    setVid((prev) => prev || next.pipelines[0]?.versions[0]?.id || "");
  }, [wid]);
  const refreshRun = useCallback(async () => {
    if (rid && wid)
      setRun(await api<RunDetail>(`/workspaces/${wid}/runs/${rid}`));
  }, [wid, rid]);
  useEffect(() => {
    api<{ id: string; name: string }[]>("/workspaces")
      .then((ws) => {
        setWorkspaces(ws);
        setWid((prev) =>
          ws.some((w) => w.id === prev) ? prev : ws[0]?.id || "",
        );
      })
      .catch((e) => setError(e.message));
    api<{
      worker_online: boolean;
      openai_configured: boolean;
      provider: string;
    }>("/health")
      .then((h) => {
        setHealth(h);
        setProvider(h.provider);
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (wid) localStorage.setItem("tracework.workspace", wid);
    setData(EMPTY);
    setVid("");
    setRid("");
    setRun(null);
    setInputs({});
    setDataset("");
    lastProposal.current = null;
    refresh().catch((e) => setError(e.message));
  }, [wid, refresh]);
  useEffect(() => {
    refreshRun().catch((e) => setError(e.message));
  }, [refreshRun]);
  useEffect(() => {
    const timer = setInterval(() => {
      refresh().catch(() => {});
      refreshRun().catch(() => {});
      api<typeof health>("/health")
        .then(setHealth)
        .catch(() => {});
    }, 1800);
    return () => clearInterval(timer);
  }, [refresh, refreshRun]);
  async function act(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }
  function chooseVersion(v: Version) {
    setVid(v.id);
    setSelectedStep("");
    setView("recipe");
  }
  function latestMapping() {
    return Object.fromEntries(
      (version?.spec.sources || []).map((s) => [
        s.name,
        data.sources.find((d) => d.name === s.name)?.versions[0]?.id || "",
      ]),
    );
  }
  function openRunDialog() {
    setInputs((prev) => (Object.keys(prev).length ? prev : latestMapping()));
    setParameters(JSON.stringify(version?.spec.parameters || {}, null, 2));
    setModal("run");
  }
  async function ask() {
    if (!question.trim()) return;
    await act("Investigating", async () => {
      await post(base + "/investigations", {
        question,
        provider,
        base_version_id: repair ? vid : null,
        failed_run_id:
          repair && run?.status === "failed" && run.version_id === vid
            ? rid
            : null,
      });
      setQuestion("");
      setRepair(false);
    });
  }
  function selectRun(id: string) {
    const r = data.runs.find((r) => r.id === id);
    setRid(id);
    setRun(null);
    if (r) {
      setVid(r.version_id);
      setInputs(r.inputs);
    }
    setSelectedStep("");
  }
  const currentWorkspace = workspaces.find((w) => w.id === wid);
  const working = data.investigations.some((i) =>
    ["queued", "running"].includes(i.status),
  );
  return (
    <div className="app">
      <aside className="rail">
        <a className="brand-mark" href="/" aria-label="Tracework home">
          <Layers size={24} />
        </a>
        <button className="rail-active" title="Workspace">
          <Command size={19} />
        </button>
        <div className="rail-bottom">
          <span title="Local workspace">LW</span>
        </div>
      </aside>
      <div className="app-body">
        <header className="topbar">
          <div className="wordmark">
            tracework<span className="alpha">LOCAL ALPHA</span>
          </div>
          <span className="top-divider" />
          <select
            aria-label="Workspace"
            value={wid}
            onChange={(e) => setWid(e.target.value)}
          >
            <option value="" disabled>
              Select workspace
            </option>
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <button
            className="icon-button"
            title="Create workspace"
            onClick={() => setModal("workspace")}
          >
            <Plus size={16} />
          </button>
          <div className="topbar-right">
            <span
              className={
                "connection " + (health?.worker_online ? "online" : "")
              }
            >
              <i />
              {health?.worker_online ? "Worker connected" : "Worker offline"}
            </span>
            <span className="provider-label">
              <FlaskConical size={13} />
              {provider === "demo" ? "No-key demo" : "OpenAI"}
            </span>
          </div>
        </header>
        {error && (
          <div className="error banner" role="alert">
            {error}
            <button onClick={() => setError("")}>Dismiss</button>
          </div>
        )}
        {notice && (
          <div className="notice banner" role="status">
            {notice}
            <button onClick={() => setNotice("")}>Dismiss</button>
          </div>
        )}
        {!wid ? (
          <main className="welcome">
            <div className="eyebrow">FROM QUESTION TO REPEATABLE WORK</div>
            <h1>
              Answers you can trace.
              <br />
              Pipelines you can run again.
            </h1>
            <p>
              Bring unfamiliar data. Investigate it with AI. Keep the SQL, the
              checks, and the evidence behind every answer.
            </p>
            <button className="primary" onClick={() => setModal("workspace")}>
              <Plus size={17} />
              Create your first workspace
            </button>
            <div className="welcome-steps">
              <span>
                01 <b>Investigate</b>Understand the source data
              </span>
              <span>
                02 <b>Build</b>Review an executable recipe
              </span>
              <span>
                03 <b>Run again</b>Understand what changed
              </span>
            </div>
          </main>
        ) : (
          <>
            <section className="workspace-header">
              <div>
                <div className="eyebrow">WORKSPACE / ANALYSIS</div>
                <h1>{currentWorkspace?.name || "Workspace"}</h1>
                <p>
                  A question becomes a recipe. Every result keeps its evidence.
                </p>
              </div>
              <div className="workspace-actions">
                <button
                  className="secondary"
                  disabled={!!busy}
                  onClick={() => {
                    setModal("upload");
                    setUploadFiles([]);
                  }}
                >
                  <Upload size={15} />
                  Add data
                </button>
                <button
                  className="primary"
                  disabled={!version || !!busy}
                  onClick={openRunDialog}
                >
                  <Play size={15} />
                  {version?.approved_at ? "Run pipeline" : "Review & run"}
                </button>
              </div>
            </section>
            <main className="workspace-grid">
              <section className="conversation">
                <div className="section-heading">
                  <MessageSquare size={16} />
                  <strong>Investigation</strong>
                  <span className="count">{data.investigations.length}</span>
                </div>
                <div className="conversation-scroll">
                  {!data.investigations.length ? (
                    <div className="intro">
                      <div className="agent-icon">
                        <Sparkles size={20} />
                      </div>
                      <h2>What’s in your data?</h2>
                      <p>
                        Ask a question across your sources. I’ll inspect the
                        data and propose a pipeline you can review.
                      </p>
                      <button
                        className="suggestion"
                        onClick={() => setQuestion(QUESTION)}
                      >
                        Which channels generate the most contribution profit?
                        <ArrowUpRight size={17} />
                      </button>
                      <div className="demo-card">
                        <span className="eyebrow">TRY THE COMPLETE STORY</span>
                        <h3>Commerce, in two batches.</h3>
                        <p>
                          Seven sources. A saved recipe. New data that changes
                          the answer.
                        </p>
                        <button
                          disabled={!!busy}
                          onClick={() =>
                            act("Loading batch one", async () => {
                              await post(base + "/demo/1");
                              setQuestion(QUESTION);
                              setNotice(
                                "Batch one loaded. Ask the suggested question to investigate the real data.",
                              );
                            })
                          }
                        >
                          {busy === "Loading batch one" ? (
                            <Loader2 size={14} className="spin" />
                          ) : (
                            <Database size={14} />
                          )}
                          Load demo batch 1<ArrowRight size={14} />
                        </button>
                      </div>
                    </div>
                  ) : (
                    data.investigations.map((i) => (
                      <InvestigationCard
                        key={i.id}
                        investigation={i}
                        onPlan={() => {
                          setVid(i.version_id!);
                          setView("recipe");
                        }}
                      />
                    ))
                  )}
                  {working && (
                    <div className="thinking">
                      <span className="pulse" />
                      Inspecting sources and recording tools…
                    </div>
                  )}
                </div>
                <div className="composer">
                  {repair && (
                    <div className="revision-note">
                      Revising v{version?.number}
                      <button onClick={() => setRepair(false)}>×</button>
                    </div>
                  )}
                  <textarea
                    aria-label="Ask about your data"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    placeholder={
                      repair
                        ? "Describe the change to this recipe…"
                        : "Ask about your data…"
                    }
                    onKeyDown={(e) => {
                      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") ask();
                    }}
                  />
                  <div>
                    <select
                      aria-label="Agent provider"
                      value={provider}
                      onChange={(e) => setProvider(e.target.value)}
                    >
                      <option value="demo">Demo · deterministic</option>
                      <option
                        value="openai"
                        disabled={!health?.openai_configured}
                      >
                        {health?.openai_configured
                          ? "OpenAI · real provider"
                          : "OpenAI · configure API key"}
                      </option>
                    </select>
                    <button
                      className="send"
                      aria-label="Send question"
                      disabled={!question.trim() || !!busy || working}
                      onClick={ask}
                    >
                      <ArrowUp size={18} />
                    </button>
                  </div>
                  <small>
                    {provider === "demo"
                      ? "No API key · commerce scenario"
                      : "Sends schemas, samples and query results to OpenAI"}
                  </small>
                </div>
              </section>
              <section className="canvas">
                <div className="canvas-tabs">
                  <div className="tabs">
                    {[
                      ["recipe", "Recipe", GitBranch],
                      ["sources", "Sources", Database],
                      ["compare", "Compare", Activity],
                    ].map(([id, label, Icon]) => (
                      <button
                        key={String(id)}
                        className={view === id ? "active" : ""}
                        onClick={() => setView(String(id))}
                      >
                        {typeof Icon !== "string" && <Icon size={15} />}
                        {String(label)}
                        {id === "sources" && <span>{data.sources.length}</span>}
                      </button>
                    ))}
                  </div>
                  <span className="saved">
                    <Check size={12} />
                    Saved locally
                  </span>
                </div>
                {view === "recipe" ? (
                  <>
                    {!version ? (
                      <div className="recipe-empty">
                        <div className="empty-graph">
                          <Database size={22} />
                          <span />
                          <GitBranch size={25} />
                          <span />
                          <Check size={23} />
                        </div>
                        <h2>Your analysis, made repeatable.</h2>
                        <p>
                          Upload data and ask a question to create your first
                          executable recipe. Every step, check and assumption
                          stays inspectable.
                        </p>
                        {data.sources.length > 0 && (
                          <span className="source-ready">
                            {data.sources.length} sources ready for
                            investigation
                          </span>
                        )}
                      </div>
                    ) : (
                      <div className="recipe-scroll">
                        <div className="recipe-title">
                          <div>
                            <span className="eyebrow">
                              VERSIONED SQL PIPELINE
                            </span>
                            <h2>{version.spec.title}</h2>
                          </div>
                          <select
                            aria-label="Pipeline version"
                            value={vid}
                            onChange={(e) => {
                              const v = versions.find(
                                (v) => v.id === e.target.value,
                              );
                              if (v) chooseVersion(v);
                            }}
                          >
                            {versions.map((v) => (
                              <option key={v.id} value={v.id}>
                                {v.spec.title} · v{v.number}
                              </option>
                            ))}
                          </select>
                        </div>
                        <p className="recipe-description">
                          {version.spec.description}
                        </p>
                        <div className="recipe-meta">
                          <span>
                            <FileCode2 size={13} />
                            {version.spec.steps.length} transformations
                          </span>
                          <span>
                            {version.spec.steps.reduce(
                              (n, s) => n + s.checks.length,
                              0,
                            )}{" "}
                            checks
                          </span>
                          <span
                            className={
                              version.approved_at ? "approved" : "pending"
                            }
                          >
                            {version.approved_at
                              ? "Approved"
                              : "Awaiting approval"}
                          </span>
                        </div>
                        <div className="source-chips">
                          {version.spec.sources.map((s) => (
                            <button
                              key={s.name}
                              onClick={() => {
                                const source = data.sources.find(
                                  (d) => d.name === s.name,
                                );
                                if (source) {
                                  setDataset(source.versions[0].dataset_id);
                                  setView("sources");
                                }
                              }}
                            >
                              <Database size={12} />
                              {s.name}
                            </button>
                          ))}
                        </div>
                        <div className="pipeline-flow">
                          {version.spec.steps.map((step, i) => {
                            const execution =
                              run?.version_id === vid
                                ? run.steps.find((s) => s.name === step.name)
                                : undefined;
                            return (
                              <button
                                key={step.name}
                                className={
                                  "step-node " +
                                  (selectedStep === step.name ? "selected" : "")
                                }
                                onClick={() => setSelectedStep(step.name)}
                              >
                                <span
                                  className={
                                    "step-number " + (execution?.status || "")
                                  }
                                >
                                  {execution?.status === "successful" ? (
                                    <Check size={16} />
                                  ) : (
                                    i + 1
                                  )}
                                </span>
                                <div>
                                  <strong>{step.title}</strong>
                                  <code>{step.name}</code>
                                  <div className="dependencies">
                                    {step.depends_on.map((d) => (
                                      <span key={d}>{d}</span>
                                    ))}
                                  </div>
                                </div>
                                <span className="step-checks">
                                  {execution ? (
                                    <Status value={execution.status} />
                                  ) : (
                                    <>
                                      {step.checks.length} checks
                                      <ArrowUpRight size={14} />
                                    </>
                                  )}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                        <details className="assumptions" open>
                          <summary>
                            Calculation & assumptions <ChevronDown size={14} />
                          </summary>
                          <ol>
                            {version.spec.assumptions.map((a) => (
                              <li key={a}>{a}</li>
                            ))}
                          </ol>
                        </details>
                        <div className="recipe-footer">
                          <span>
                            <code>{short(version.hash)}</code> · immutable v
                            {version.number}
                          </span>
                          <div>
                            <button
                              onClick={() => {
                                setDraft(JSON.stringify(version.spec, null, 2));
                                setModal("edit");
                              }}
                            >
                              <FileCode2 size={14} />
                              Edit recipe
                            </button>
                            <button
                              onClick={() => {
                                setRepair(true);
                                setQuestion(
                                  run?.status === "failed"
                                    ? "Repair the pipeline: accept spend_cents and remove exact duplicate order records."
                                    : "",
                                );
                              }}
                            >
                              <Sparkles size={14} />
                              Request change
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </>
                ) : view === "sources" ? (
                  <div className="sources-view">
                    <div className="sources-heading">
                      <div>
                        <h2>Source library</h2>
                        <p>Original uploads stay immutable.</p>
                      </div>
                      <button
                        className="secondary"
                        disabled={!!busy}
                        onClick={() =>
                          act("Loading batch two", async () => {
                            await post(base + "/demo/2");
                            setNotice(
                              "Batch two loaded. Open Run pipeline and explicitly select the new input versions. The saved SQL is unchanged.",
                            );
                          })
                        }
                      >
                        <RotateCcw size={14} />
                        Load demo batch 2
                      </button>
                    </div>
                    {!data.sources.length ? (
                      <Empty title="No sources yet">
                        Upload CSV or Parquet files, or load the commerce demo.
                      </Empty>
                    ) : (
                      <>
                        <div className="source-list">
                          {data.sources.map((source) => (
                            <div
                              className={
                                "source-row " +
                                (source.versions.some(
                                  (v) => v.dataset_id === dataset,
                                )
                                  ? "selected"
                                  : "")
                              }
                              key={source.id}
                            >
                              <Database size={16} />
                              <button
                                onClick={() => {
                                  setDataset(source.versions[0].dataset_id);
                                  setEvidence(-1);
                                }}
                              >
                                <strong>{source.name}</strong>
                                <small>
                                  {source.versions[0].rows.toLocaleString()}{" "}
                                  rows · {source.versions.length} version
                                  {source.versions.length === 1 ? "" : "s"}
                                </small>
                              </button>
                              <select
                                aria-label={`${source.name} version`}
                                value={
                                  source.versions.find(
                                    (v) => v.dataset_id === dataset,
                                  )?.dataset_id || source.versions[0].dataset_id
                                }
                                onChange={(e) => {
                                  setDataset(e.target.value);
                                  setEvidence(-1);
                                }}
                              >
                                {source.versions.map((v, i) => (
                                  <option key={v.id} value={v.dataset_id}>
                                    v{source.versions.length - i} ·{" "}
                                    {short(v.hash)}
                                  </option>
                                ))}
                              </select>
                            </div>
                          ))}
                        </div>
                        <DataPreview
                          key={
                            dataset || data.sources[0].versions[0].dataset_id
                          }
                          wid={wid}
                          did={
                            dataset || data.sources[0].versions[0].dataset_id
                          }
                          highlight={evidence}
                        />
                      </>
                    )}
                  </div>
                ) : view === "output" ? (
                  <div className="sources-view">
                    <div className="sources-heading">
                      <h2>Evidence & output</h2>
                      <button onClick={() => setView("recipe")}>
                        Back to recipe
                      </button>
                    </div>
                    {dataset && (
                      <DataPreview
                        wid={wid}
                        did={dataset}
                        highlight={evidence}
                      />
                    )}
                  </div>
                ) : (
                  <CompareView wid={wid} runs={data.runs} />
                )}
              </section>
              <RunInspector
                wid={wid}
                runs={data.runs}
                run={run}
                version={version}
                selectedStep={selectedStep}
                onSelectRun={selectRun}
                onStep={setSelectedStep}
                onOutput={(did, row = -1) => {
                  setDataset(did);
                  setEvidence(row);
                  setView("output");
                }}
                onCancel={() =>
                  act("Cancelling", async () => {
                    await post(base + `/runs/${rid}/cancel`);
                    await refreshRun();
                  })
                }
                onRepair={() => {
                  if (run) setVid(run.version_id);
                  setRepair(true);
                  setQuestion(
                    "Repair the pipeline: accept spend_cents and remove exact duplicate order records.",
                  );
                }}
              />
            </main>
          </>
        )}
        {modal === "workspace" && (
          <Modal title="Create a workspace" onClose={() => setModal("")}>
            <p>Keep sources, recipes and runs together.</p>
            <label>
              Workspace name
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </label>
            <button
              className="primary"
              disabled={!newName.trim() || !!busy}
              onClick={() =>
                act("Creating workspace", async () => {
                  const w = await post<{ id: string; name: string }>(
                    "/workspaces",
                    { name: newName },
                  );
                  setWorkspaces((ws) => [...ws, w]);
                  setWid(w.id);
                  setModal("");
                })
              }
            >
              Create workspace
              <ArrowRight size={16} />
            </button>
          </Modal>
        )}
        {modal === "upload" && (
          <Modal title="Add source data" onClose={() => setModal("")}>
            <p>
              CSV or Parquet · up to 50 MiB per file. Reuse a logical name to
              add a new immutable version.
            </p>
            <label className="upload-drop">
              <Upload size={24} />
              <strong>Choose your data files</strong>
              <input
                aria-label="Upload files"
                type="file"
                multiple
                accept=".csv,.parquet"
                onChange={(e) =>
                  setUploadFiles(Array.from(e.target.files || []))
                }
              />
            </label>
            {uploadFiles.length > 0 && (
              <p>{uploadFiles.map((f) => f.name).join(", ")}</p>
            )}
            <label>
              Logical source name{" "}
              {uploadFiles.length !== 1 &&
                "(uses file names for multiple uploads)"}
              <input
                value={sourceName}
                onChange={(e) => setSourceName(e.target.value)}
                placeholder="e.g. orders"
                disabled={uploadFiles.length !== 1}
              />
            </label>
            <button
              className="primary"
              disabled={!uploadFiles.length || !!busy}
              onClick={() =>
                act("Profiling uploads", async () => {
                  for (const file of uploadFiles) {
                    const form = new FormData();
                    form.append("file", file);
                    form.append(
                      "name",
                      uploadFiles.length === 1 && sourceName
                        ? sourceName
                        : file.name
                            .replace(/\.[^.]+$/, "")
                            .toLowerCase()
                            .replace(/[^a-z0-9_]/g, "_"),
                    );
                    await api(base + "/sources", {
                      method: "POST",
                      body: form,
                    });
                  }
                  setModal("");
                  setView("sources");
                  setNotice(
                    `${uploadFiles.length} files uploaded and profiled.`,
                  );
                })
              }
            >
              {busy === "Profiling uploads" ? (
                <Loader2 size={16} className="spin" />
              ) : (
                <Upload size={16} />
              )}
              Upload & profile
            </button>
          </Modal>
        )}
        {modal === "run" && version && (
          <Modal
            title={`Run pipeline · v${version.number}`}
            wide
            onClose={() => setModal("")}
          >
            <p>
              Map each recipe input to an immutable source version. This
              executes the saved SQL without an LLM.
            </p>
            <div className="mapping-title">
              <strong>Source mapping</strong>
              <button onClick={() => setInputs(latestMapping())}>
                Use latest versions
              </button>
            </div>
            <div className="mapping">
              {version.spec.sources.map((s) => (
                <label key={s.name}>
                  <code>{s.name}</code>
                  <ArrowRight size={14} />
                  <select
                    aria-label={`Map ${s.name}`}
                    value={inputs[s.name] || ""}
                    onChange={(e) =>
                      setInputs({ ...inputs, [s.name]: e.target.value })
                    }
                  >
                    <option value="">Select source version…</option>
                    {data.sources.map((source) => (
                      <optgroup label={source.name} key={source.id}>
                        {source.versions.map((v, i) => (
                          <option value={v.id} key={v.id}>
                            {source.name} · v{source.versions.length - i} ·{" "}
                            {short(v.hash)} · {v.rows} rows
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            <details className="run-settings">
              <summary>
                <Settings2 size={14} />
                Parameters & execution limits
              </summary>
              <label>
                Parameters (JSON)
                <textarea
                  className="code-editor"
                  value={parameters}
                  onChange={(e) => setParameters(e.target.value)}
                />
              </label>
              <label>
                Timeout in seconds
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={timeout}
                  onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
                />
              </label>
              <p>
                512 MiB DuckDB memory · 2 threads · 100,000 output rows per step
              </p>
            </details>
            {!version.approved_at && (
              <div className="approval-callout">
                <Check size={17} />
                <p>
                  By approving, you accept the SQL, checks and assumptions shown
                  in this recipe. Approval is recorded for v{version.number}{" "}
                  only.
                </p>
              </div>
            )}
            <button
              className="primary"
              disabled={
                !!busy || version.spec.sources.some((s) => !inputs[s.name])
              }
              onClick={() =>
                act("Queueing run", async () => {
                  const params = JSON.parse(parameters);
                  if (!version.approved_at)
                    await post(base + `/versions/${vid}/approve`);
                  const r = await post<{ id: string }>(base + "/runs", {
                    version_id: vid,
                    inputs,
                    parameters: params,
                    settings: { timeout_seconds: timeout },
                    request_key: crypto.randomUUID(),
                  });
                  setRid(r.id);
                  setRun(null);
                  setModal("");
                  setNotice(
                    "Run queued. Progress and checks appear in the run inspector.",
                  );
                })
              }
            >
              <Play size={15} />
              {version.approved_at
                ? "Queue run with these inputs"
                : "Approve this version & queue run"}
            </button>
          </Modal>
        )}
        {modal === "edit" && version && (
          <Modal
            title={`Create a revision of v${version.number}`}
            wide
            onClose={() => setModal("")}
          >
            <p>
              Edit SQL, dependencies, checks, contracts or assumptions. Saving
              creates a new unapproved version; previous versions and runs
              remain available.
            </p>
            <textarea
              aria-label="Pipeline JSON"
              className="code-editor full-editor"
              spellCheck={false}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <button
              className="primary"
              disabled={!!busy}
              onClick={() =>
                act("Validating revision", async () => {
                  const v = await post<Version>(base + "/pipelines", {
                    spec: JSON.parse(draft),
                    parent_id: vid,
                  });
                  setVid(v.id);
                  setModal("");
                  setNotice(
                    "New immutable version created. Review and approve before running.",
                  );
                })
              }
            >
              <GitBranch size={16} />
              Save new version
            </button>
          </Modal>
        )}
        {busy && (
          <div className="busy-toast" role="status">
            <Loader2 className="spin" size={16} />
            {busy}…
          </div>
        )}
      </div>
    </div>
  );
}
function InvestigationCard({
  investigation: i,
  onPlan,
}: {
  investigation: Investigation;
  onPlan: () => void;
}) {
  return (
    <article className="investigation-card">
      <div className="user-message">
        <span className="avatar">YOU</span>
        <p>{i.question}</p>
      </div>
      <div className="agent-message">
        <span className="agent-badge">
          <Layers size={14} />
          TRACEWORK <small>{i.provider === "demo" ? "DEMO" : "AI"}</small>
        </span>
        <Status value={i.status} />
        {i.events.length > 0 && (
          <div className="tool-list">
            {i.events.map((e) => (
              <details key={e.id}>
                <summary>
                  <Check size={12} />
                  {e.tool.replaceAll("_", " ")}
                  <ChevronDown size={12} />
                </summary>
                <pre>
                  {JSON.stringify(
                    { arguments: e.arguments, response: e.response },
                    null,
                    2,
                  )}
                </pre>
              </details>
            ))}
          </div>
        )}
        {i.message && <p>{i.message}</p>}
        {i.error && <p className="error">{i.error}</p>}
        {i.version_id && (
          <button className="plan-link" onClick={onPlan}>
            <GitBranch size={15} />
            Inspect proposed recipe
            <ArrowRight size={15} />
          </button>
        )}
      </div>
    </article>
  );
}
