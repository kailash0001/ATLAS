import { ChevronRight } from "lucide-react";
import {
  Row,
  short,
  date,
  text,
  Badge,
  Empty,
  Panel,
  Evidence,
  Table,
  Timeline,
} from "./components";
type Props = {
  affected: (r: Row) => string;
  section: string;
  selectedLive: Row;
  versions: Row[];
  rows: (key: string) => Row[];
  health: (r: Row) => string;
  setActionError: (s: string) => void;
  setRetrain: (b: boolean) => void;
  buttons: (r: Row, k: string) => React.ReactNode;
  incidents: Row[];
  deployments: Row[];
  modelName: (id: string) => string;
  version: (id: string) => Row | undefined;
  incidentColumns: [string, (r: Row) => React.ReactNode][];
};
export function Inspector({
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
}: Props) {
  const r = selectedLive!;
  if (section === "models") {
    const mv = versions.filter((v) => v.model_id === r.id),
      reports = rows("reports").filter((x) =>
        mv.some((v) => v.id === x.model_version_id),
      );
    return (
      <>
        <div className="detail-grid">
          <Panel title="Model identity">
            <div className="panel-body">
              <dl>
                {[
                  ["Model", r.name],
                  ["Owner", r.owner],
                  ["Use case", r.use_case],
                  ["Environment", r.environment],
                  ["Registry", r.registry_name],
                  ["Created", date(r.created_at)],
                ].map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
              <div className="actions">
                <button
                  onClick={() => {
                    setActionError("");
                    setRetrain(true);
                  }}
                >
                  Request retraining
                </button>
              </div>
            </div>
          </Panel>
          <Panel title="Reliability" meta="Latest recorded report">
            <div className="panel-body">
              <Badge value={health(r)} />
              <p className="footer-note">
                Health reflects the latest stored evidence, not an inferred
                assessment of every version.
              </p>
              {reports[0] && <Evidence value={reports[0].evidence} />}
            </div>
          </Panel>
        </div>
        <Panel title="Versions & lineage">
          <Table
            rows={mv}
            columns={[
              ["Version", (v) => <code>v{v.version}</code>],
              ["Status", (v) => <Badge value={v.status} />],
              ["Training run", (v) => <code>{short(v.training_run_id)}</code>],
              [
                "Algorithm",
                (v) =>
                  rows("runs").find((x) => x.id === v.training_run_id)
                    ?.algorithm,
              ],
              [
                "Dataset",
                (v) => (
                  <code>
                    {short(
                      rows("runs").find((x) => x.id === v.training_run_id)
                        ?.dataset_version_id,
                    )}
                  </code>
                ),
              ],
              ["Created", (v) => date(v.created_at)],
            ]}
          />
          <div className="panel-body">
            <Evidence
              value={{
                versions: mv,
                runs: rows("runs").filter((x) => x.model_id === r.id),
              }}
            />
          </div>
        </Panel>
        <Panel title="Related incidents">
          <Table
            rows={incidents.filter((i) =>
              mv.some((v) => v.id === i.model_version_id),
            )}
            columns={incidentColumns}
          />
        </Panel>
        <Panel title="Deployment history">
          <Table
            rows={deployments.filter((d) => d.model_id === r.id)}
            columns={[
              ["Deployment", (d) => short(d.id)],
              ["Status", (d) => <Badge value={d.status} />],
              ["Traffic", (d) => `${d.traffic_percent}%`],
              ["Started", (d) => date(d.started_at)],
            ]}
          />
        </Panel>
      </>
    );
  }
  if (section === "incidents") {
    const inv = rows("investigations").filter((i) => i.incident_id === r.id);
    const report = rows("reports").find((x) => x.id === r.latest_report_id);
    return (
      <div className="detail-grid">
        <Panel title="Incident inspector" meta={<Badge value={r.severity} />}>
          <div className="panel-body">
            <dl>
              {[
                ["Affected model", affected(r)],
                ["Detected issue", r.incident_type],
                ["Feature", r.feature],
                ["Status", r.status],
                ["First seen", date(r.created_at)],
                ["Occurrences", r.occurrences],
                ["Category", inv[0]?.category || "Not investigated"],
              ].map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
            {buttons(r, "incidents")}
            <Evidence value={report?.evidence || { available: false }} />
          </div>
        </Panel>
        <Panel title="Investigation & timeline">
          <div className="panel-body">
            {inv[0] ? (
              <>
                <Badge value={inv[0].category} />
                <pre>{inv[0].explanation}</pre>
                <Evidence value={inv[0].conclusion} />
              </>
            ) : (
              <Empty>
                No investigation yet. Collect the evidence to classify this
                incident.
              </Empty>
            )}
            <Timeline
              records={rows("audit").filter(
                (a) =>
                  a.resource_id === r.id ||
                  inv.some((i) => i.id === a.resource_id),
              )}
            />
          </div>
        </Panel>
      </div>
    );
  }
  if (section === "deployments")
    return (
      <>
        <Panel
          title={`${modelName(r.model_id)} · progressive rollout`}
          meta={<Badge value={r.status} />}
        >
          <div className="panel-body">
            <div className="status-line">
              <span>Previous v{version(r.previous_id)?.version}</span>
              <ChevronRight size={14} />
              <span>Candidate v{version(r.candidate_id)?.version}</span>
              <span className="tag">{r.backend}</span>
            </div>
            <div className="steps">
              {[10, 25, 50, 100].map((p) => (
                <div
                  key={p}
                  className={`step ${p < r.traffic_percent ? "done" : p === r.traffic_percent ? "current" : ""}`}
                >
                  {p}%
                </div>
              ))}
            </div>
            <div className="traffic">
              <span style={{ width: `${r.traffic_percent}%` }} />
            </div>
            <div className="status-line">
              <strong>{r.traffic_percent}% candidate</strong>
              <small>{100 - r.traffic_percent}% previous version</small>
            </div>
            {buttons(r, "deployments")}
          </div>
        </Panel>
        <div className="detail-grid">
          <Panel title="Measured health">
            <div className="panel-body">
              <Badge value={r.health?.status || "AWAITING_TRAFFIC"} />
              <dl style={{ marginTop: 20 }}>
                {[
                  ["Requests", r.health?.requests],
                  ["Labels", r.health?.labels],
                  ["p95 latency (ms)", r.health?.p95_ms],
                  ["Error ratio", r.health?.error_rate],
                  ["F1", r.health?.f1],
                  ["MAPE (%)", r.health?.mape_percent],
                ].map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k}</dt>
                    <dd className="mono">{text(v)}</dd>
                  </div>
                ))}
              </dl>
              <Evidence value={r.health} />
            </div>
          </Panel>
          <Panel title="Deployment timeline">
            <div className="panel-body">
              <Timeline
                records={rows("audit").filter((a) => a.resource_id === r.id)}
              />
              <Evidence value={r.policy} />
            </div>
          </Panel>
        </div>
      </>
    );
  if (section === "pipelines" || section === "governance")
    return (
      <Panel
        title={`${modelName(r.model_id)} · candidate review`}
        meta={<Badge value={r.status} />}
      >
        <div className="panel-body">
          <dl>
            <dt>Requested by</dt>
            <dd>{r.requested_by}</dd>
            <dt>Reason</dt>
            <dd>{r.reason}</dd>
            <dt>Algorithm</dt>
            <dd>{r.algorithm}</dd>
            <dt>Dataset</dt>
            <dd className="mono">{r.dataset_fingerprint}</dd>
          </dl>
          {buttons(r, "pipelines")}
          <div style={{ marginTop: 24 }}>
            <Table
              rows={(r.results?.gates || []).map((g: any) => ({
                ...g,
                id: g.name,
              }))}
              columns={[
                ["Quality gate", (g) => g.name.replaceAll("_", " ")],
                [
                  "Result",
                  (g) => <Badge value={g.passed ? "PASSED" : "FAILED"} />,
                ],
                [
                  "Evidence",
                  (g) => (
                    <span className="mono">
                      {Object.entries(g.evidence)
                        .filter(([, v]) => typeof v !== "object")
                        .map(([k, v]) => `${k}: ${text(v)}`)
                        .join(" · ")}
                    </span>
                  ),
                ],
              ]}
            />
          </div>
          <Evidence value={r} />
        </div>
      </Panel>
    );
  return (
    <Panel title="Record details">
      <div className="panel-body">
        <Evidence value={r} />
      </div>
    </Panel>
  );
}
