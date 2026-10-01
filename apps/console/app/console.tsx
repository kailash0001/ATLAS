"use client";
import { Workspaces } from "./workspaces";
import { Inspector } from "./inspectors";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  Box,
  ChevronRight,
  CircleHelp,
  Database,
  GitBranch,
  Layers,
  LayoutDashboard,
  ListChecks,
  Menu,
  RefreshCw,
  Search,
  Settings,
  Shield,
  ShieldCheck,
  Terminal,
  TriangleAlert,
  Workflow,
  X,
} from "lucide-react";

import {
  Row,
  State,
  Action,
  navigation,
  short,
  date,
  text,
  Badge,
  Empty,
  Panel,
  Evidence,
  Table,
  Trend,
  Timeline,
} from "./components";
export default function Console() {
  const pathname = usePathname();
  const section = pathname.split("/")[1] || "overview";
  const title =
    navigation.find(([n]) => n.toLowerCase() === section)?.[0] || "Overview";
  const [state, setState] = useState<State | null>(null),
    [metrics, setMetrics] = useState<any>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [filter, setFilter] = useState(""),
    [selected, setSelected] = useState<Row | null>(null),
    [action, setAction] = useState<Action | null>(null),
    [reason, setReason] = useState(""),
    [busy, setBusy] = useState(false),
    [actionError, setActionError] = useState(""),
    [notice, setNotice] = useState(""),
    [mobile, setMobile] = useState(false),
    [command, setCommand] = useState(""),
    [retrain, setRetrain] = useState(false);
  const actionDialog = useRef<HTMLDialogElement>(null),
    commandDialog = useRef<HTMLDialogElement>(null),
    retrainDialog = useRef<HTMLDialogElement>(null);
  const refresh = useCallback(async () => {
    try {
      const r = await fetch("/api/state", { cache: "no-store" });
      if (!r.ok)
        throw new Error((await r.json()).detail || "Control API unavailable");
      setState(await r.json());
      setError("");
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Unable to load platform state",
      );
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const r = await fetch("/api/monitoring");
        if (live) setMetrics(r.ok ? await r.json() : { available: false });
      } catch {
        if (live) setMetrics({ available: false });
      }
    };
    load();
    const timer = setInterval(load, 30000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    setSelected(null);
    setFilter("");
    setMobile(false);
  }, [section]);
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        commandDialog.current?.showModal();
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
  useEffect(() => {
    if (action) actionDialog.current?.showModal();
  }, [action]);
  useEffect(() => {
    if (retrain) retrainDialog.current?.showModal();
  }, [retrain]);
  const rows = (key: string): Row[] => state?.[key] || [];
  const models = rows("models"),
    versions = rows("versions"),
    incidents = rows("incidents"),
    deployments = rows("deployments"),
    pipelines = rows("pipelines");
  const modelName = (id: string) =>
    models.find((m) => m.id === id)?.name || short(id);
  const version = (id: string) => versions.find((v) => v.id === id);
  const affected = (r: Row) =>
    modelName(version(r.model_version_id)?.model_id || r.model_id);
  const filtered = (items: Row[]) =>
    items.filter((r) =>
      JSON.stringify(r).toLowerCase().includes(filter.toLowerCase()),
    );
  const health = (model: Row) =>
    rows("reports").find(
      (r) => version(r.model_version_id)?.model_id === model.id,
    )?.severity || "UNASSESSED";
  const open = (title: string, path: string) => {
    setReason("");
    setActionError("");
    setAction({ title, path });
  };
  const mutate = async (path: string, body: Record<string, unknown>) => {
    const r = await fetch(`/api/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const result = await r.json();
    if (!r.ok)
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "Invalid operation; check required fields",
      );
    return result;
  };
  const perform = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!action) return;
    setBusy(true);
    setActionError("");
    try {
      await mutate(action.path, { reason, ...action.extra });
      setNotice(`${action.title} completed. State refreshed.`);
      actionDialog.current?.close();
      setAction(null);
      await refresh();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const buttons = (r: Row, kind: string) => (
    <div className="actions">
      {kind === "incidents" && (
        <>
          <button
            onClick={() =>
              open("Investigate incident", `incidents/${r.id}/investigate`)
            }
          >
            Investigate
          </button>
          {r.status === "OPEN" && (
            <button
              onClick={() =>
                open("Acknowledge incident", `incidents/${r.id}/acknowledge`)
              }
            >
              Acknowledge
            </button>
          )}
          {r.status !== "RESOLVED" && (
            <button
              onClick={() =>
                open("Resolve incident", `incidents/${r.id}/resolve`)
              }
            >
              Resolve
            </button>
          )}
        </>
      )}
      {kind === "pipelines" && (
        <>
          {["REQUESTED", "VALIDATED", "TRAINED"].includes(r.status) && (
            <button
              onClick={() =>
                open("Schedule in Airflow", `pipelines/${r.id}/run`)
              }
            >
              Run in Airflow
            </button>
          )}
          {r.status === "AWAITING_APPROVAL" && (
            <>
              <button
                className="primary"
                onClick={() =>
                  open("Approve candidate", `pipelines/${r.id}/approve`)
                }
              >
                Approve
              </button>
              <button
                className="danger"
                onClick={() =>
                  open("Reject candidate", `pipelines/${r.id}/reject`)
                }
              >
                Reject
              </button>
            </>
          )}
          {r.status === "APPROVED" && (
            <button
              className="primary"
              onClick={() =>
                open("Start 10% canary", `pipelines/${r.id}/deploy`)
              }
            >
              Start canary
            </button>
          )}
        </>
      )}
      {kind === "deployments" && (
        <>
          {["CANARY", "PROMOTED"].includes(r.status) && (
            <button
              onClick={() =>
                open("Observe deployment", `deployments/${r.id}/observe`)
              }
            >
              Observe health
            </button>
          )}
          {r.status === "CANARY" && (
            <button
              className="primary"
              onClick={() =>
                open(
                  r.traffic_percent === 100
                    ? "Promote candidate"
                    : "Advance traffic",
                  `deployments/${r.id}/advance`,
                )
              }
            >
              {r.traffic_percent === 100 ? "Promote" : "Advance traffic"}
            </button>
          )}
          {["PREPARING", "CANARY", "PROMOTED"].includes(r.status) && (
            <button
              className="danger"
              onClick={() =>
                open("Roll back deployment", `deployments/${r.id}/rollback`)
              }
            >
              Roll back
            </button>
          )}
        </>
      )}
    </div>
  );
  const modelColumns: [string, (r: Row) => React.ReactNode][] = [
    [
      "Model",
      (r) => (
        <>
          <span>{r.name}</span>
          <span className="subline">{r.use_case}</span>
        </>
      ),
    ],
    ["Health", (r) => <Badge value={health(r)} />],
    [
      "Champion",
      (r) => (
        <span className="mono">
          {versions.find((v) => v.model_id === r.id && v.status === "champion")
            ?.version
            ? `v${versions.find((v) => v.model_id === r.id && v.status === "champion")?.version}`
            : "Not promoted"}
        </span>
      ),
    ],
    ["Owner", (r) => r.owner],
    ["Risk", (r) => <Badge value={r.risk_level} />],
  ];
  const incidentColumns: [string, (r: Row) => React.ReactNode][] = [
    [
      "Incident",
      (r) => (
        <>
          <span className="mono">INC-{short(r.id)}</span>
          <span className="subline">{affected(r)}</span>
        </>
      ),
    ],
    ["Severity", (r) => <Badge value={r.severity} />],
    ["Signal", (r) => r.incident_type.replaceAll("_", " ").toLowerCase()],
    ["Feature", (r) => <code>{r.feature}</code>],
    ["State", (r) => <Badge value={r.status} />],
    ["Updated", (r) => date(r.updated_at)],
  ];
  const selectedLive =
    selected &&
    (rows(section === "governance" ? "pipelines" : section).find(
      (r) => r.id === selected.id,
    ) ||
      selected);
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <div className="shell">
        <aside className={`sidebar ${mobile ? "open" : ""}`}>
          <Link className="brand" href="/">
            <Shield size={27} />
            <span>
              ATLAS
              <small>RELIABILITY PLATFORM</small>
            </span>
          </Link>
          <div className="workspace">
            <span>DEV</span>
            <div>
              Local workspace
              <small className="subline">
                {state?.environment || "Connecting"}
              </small>
            </div>
          </div>
          <div className="nav-label">Control plane</div>
          <nav aria-label="Main navigation">
            {navigation.map(([name, Icon]) => (
              <Link
                key={name}
                className={name === title ? "active" : ""}
                aria-current={name === title ? "page" : undefined}
                href={
                  name === "Overview" ? "/overview" : `/${name.toLowerCase()}`
                }
              >
                <Icon size={16} />
                {name}
              </Link>
            ))}
          </nav>
          <footer>
            <span className="good-text">●</span> Local-first infrastructure
            <br />
            <span className="mono">ATLAS / 0.6.0</span>
            <br />
            Six phases. One platform.
            <br />
            <button
              onClick={async () => {
                await fetch("/api/auth/logout", { method: "POST" });
                window.location.assign("/login");
              }}
              style={{ marginTop: 12, padding: "6px 10px", fontSize: 11 }}
            >
              Sign out
            </button>
          </footer>
        </aside>
        <div>
          <header className="topbar">
            <div className="crumb">
              <button
                className="mobile-menu"
                aria-label="Toggle navigation"
                onClick={() => setMobile(!mobile)}
              >
                <Menu size={16} />
              </button>
              <span>Workspace</span>
              <ChevronRight size={12} />
              <strong>{title}</strong>
            </div>
            <div className="toolbar">
              <button
                aria-label="Open command palette"
                onClick={() => commandDialog.current?.showModal()}
              >
                <Search size={14} />
                <span className="search-label">Jump to…</span>
                <small>Ctrl K</small>
              </button>
              <span className="tag">
                <i className="dot" />
                Development
              </span>
            </div>
          </header>
          <main className="content" id="main">
            <div className="page-head">
              <div>
                <div className="eyebrow">ATLAS / {title}</div>
                <h1>
                  {selectedLive
                    ? selectedLive.name ||
                      `${title.slice(0, -1)} ${short(selectedLive.id)}`
                    : title === "Overview"
                      ? "Platform overview"
                      : title}
                </h1>
                <p>
                  {title === "Overview"
                    ? "Model reliability, operational signals, and the actions that follow."
                    : {
                        Models:
                          "Versioned workloads and their evidence, from training to production.",
                        Deployments:
                          "Measured canary progression with a clear path back.",
                        Incidents:
                          "Investigate the signal. Establish the cause. Choose the response.",
                        Datasets:
                          "Immutable sources, split integrity, and training provenance.",
                        Pipelines:
                          "Retraining requests, orchestration, and candidate quality gates.",
                        Monitoring:
                          "Live Prometheus telemetry. No generated measurements.",
                        Governance:
                          "Review candidate evidence and explicit approval decisions.",
                        Audit: "A chronological record of platform operations.",
                        Settings:
                          "Runtime configuration and the limits of automation.",
                      }[title]}
                </p>
              </div>
              <button onClick={refresh} aria-label="Refresh platform state">
                <RefreshCw size={14} />
                Refresh
              </button>
            </div>
            {error && (
              <div role="alert" className="alert error">
                <span>
                  {error}
                  {state ? " Showing the last successful snapshot." : ""}
                </span>
                <button onClick={refresh}>Retry</button>
              </div>
            )}
            {notice && (
              <div role="status" className="toast">
                {notice}
                <button
                  style={{
                    float: "right",
                    padding: 0,
                    border: 0,
                    background: "none",
                  }}
                  aria-label="Dismiss notification"
                  onClick={() => setNotice("")}
                >
                  <X size={14} />
                </button>
              </div>
            )}
            {loading && !state ? (
              <>
                <div className="skeleton" aria-label="Loading platform state" />
                <div className="skeleton" />
              </>
            ) : !state ? (
              <Empty>
                The control API is not available. Start it and select Refresh.
              </Empty>
            ) : selectedLive ? (
              <>
                <div className="detail-head">
                  <button onClick={() => setSelected(null)}>
                    <ArrowLeft size={14} />
                    Back to {title.toLowerCase()}
                  </button>
                  <code>{selectedLive.id}</code>
                </div>
                <Inspector
                  {...{
                    affected,
                    section,
                    selectedLive,
                    versions,
                    rows,
                    health,
                    setActionError,
                    setRetrain,
                    buttons,
                    incidents,
                    deployments,
                    modelName,
                    version,
                    incidentColumns,
                  }}
                  selectedLive={selectedLive}
                />
              </>
            ) : (
              <>
                <Workspaces
                  {...{
                    title,
                    state,
                    metrics,
                    models,
                    incidents,
                    deployments,
                    pipelines,
                    rows,
                    health,
                    filter,
                    setFilter,
                    filtered,
                    setSelected,
                    modelColumns,
                    incidentColumns,
                    version,
                    modelName,
                  }}
                  state={state}
                />
              </>
            )}
            <div className="footer-note">
              {state
                ? `Snapshot ${date(state.generated_at)} · refresh every 10 seconds · up to 100 recent records per collection`
                : "Connecting to the control API"}
              <br />
              Unknown and unavailable states are preserved. Model health comes
              from recorded evidence.
            </div>
          </main>
        </div>
      </div>
      <dialog
        ref={actionDialog}
        onCancel={() => setAction(null)}
        aria-labelledby="action-title"
      >
        <form onSubmit={perform}>
          <h2 id="action-title">{action?.title}</h2>
          <p className="muted">
            The backend will recheck policy, evidence, and current state before
            applying this operation.
          </p>
          <label htmlFor="reason">Review reason</label>
          <textarea
            id="reason"
            required
            minLength={3}
            maxLength={2000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            autoFocus
          />
          {actionError && (
            <p role="alert" className="alert error">
              {actionError}
            </p>
          )}
          <div className="actions">
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                actionDialog.current?.close();
                setAction(null);
              }}
            >
              Cancel
            </button>
            <button className="primary" disabled={busy}>
              {busy ? "Applying…" : "Confirm operation"}
            </button>
          </div>
        </form>
      </dialog>
      <dialog ref={commandDialog} aria-labelledby="command-title">
        <h2 id="command-title">Jump to a workspace</h2>
        <input
          aria-label="Search navigation"
          autoFocus
          placeholder="Search pages…"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
        />
        <div className="command-list">
          {navigation
            .filter(([n]) => n.toLowerCase().includes(command.toLowerCase()))
            .map(([name]) => (
              <Link
                key={name}
                onClick={() => commandDialog.current?.close()}
                href={
                  name === "Overview" ? "/overview" : `/${name.toLowerCase()}`
                }
              >
                {name}
              </Link>
            ))}
        </div>
        <div className="actions">
          <button onClick={() => commandDialog.current?.close()}>
            Close · Esc
          </button>
        </div>
      </dialog>
      <dialog
        ref={retrainDialog}
        onCancel={() => setRetrain(false)}
        aria-labelledby="retrain-title"
      >
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const form = new FormData(e.currentTarget);
            setBusy(true);
            setActionError("");
            try {
              await mutate("retraining", {
                model: selected?.name,
                baseline: Number(form.get("baseline")),
                dataset_fingerprint: form.get("dataset"),
                algorithm: form.get("algorithm"),
                verification_id: form.get("verification"),
                reason: form.get("reason"),
              });
              retrainDialog.current?.close();
              setRetrain(false);
              setNotice(
                "Retraining request created. Open Pipelines to schedule it.",
              );
              await refresh();
            } catch (e) {
              setActionError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <h2 id="retrain-title">Request retraining</h2>
          <p className="muted">
            {selected?.name} · validated data and fresh test verification
            required.
          </p>
          <label htmlFor="baseline">Baseline version</label>
          <select id="baseline" name="baseline" required>
            {versions
              .filter(
                (v) =>
                  v.model_id === selected?.id &&
                  ["champion", "candidate"].includes(v.status),
              )
              .map((v) => (
                <option key={v.id} value={v.version}>
                  v{v.version} · {v.status}
                </option>
              ))}
          </select>
          <label htmlFor="dataset">Dataset fingerprint</label>
          <input
            id="dataset"
            name="dataset"
            required
            pattern="[a-f0-9]{64}"
            placeholder="64-character immutable dataset hash"
          />
          <label htmlFor="algorithm">Algorithm</label>
          <select id="algorithm" name="algorithm">
            <option
              value={
                selected?.name === "energy-demand"
                  ? "random_forest_regressor"
                  : "random_forest"
              }
            >
              Random forest
            </option>
          </select>
          <label htmlFor="verification">Test verification</label>
          <select id="verification" name="verification" required>
            {rows("verifications")
              .filter((v) => v.passed)
              .map((v) => (
                <option key={v.id} value={v.id}>
                  {short(v.id)} · {date(v.created_at)}
                </option>
              ))}
          </select>
          <label htmlFor="retrain-reason">Reason</label>
          <textarea id="retrain-reason" name="reason" minLength={3} required />
          {actionError && (
            <p role="alert" className="alert error">
              {actionError}
            </p>
          )}
          <div className="actions">
            <button
              type="button"
              onClick={() => {
                retrainDialog.current?.close();
                setRetrain(false);
              }}
            >
              Cancel
            </button>
            <button className="primary" disabled={busy}>
              {busy ? "Creating…" : "Create request"}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
