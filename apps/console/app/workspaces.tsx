import Link from "next/link";
import {
  Box,
  ShieldCheck,
  TriangleAlert,
  GitBranch,
  ArrowUpRight,
} from "lucide-react";
import {
  Row,
  State,
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
type Props = {
  title: string;
  state: State;
  metrics: any;
  models: Row[];
  incidents: Row[];
  deployments: Row[];
  pipelines: Row[];
  rows: (k: string) => Row[];
  health: (r: Row) => string;
  filter: string;
  setFilter: (s: string) => void;
  filtered: (rows: Row[]) => Row[];
  setSelected: (r: Row) => void;
  modelColumns: [string, (r: Row) => React.ReactNode][];
  incidentColumns: [string, (r: Row) => React.ReactNode][];
  version: (id: string) => Row | undefined;
  modelName: (id: string) => string;
};
export function Workspaces({
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
}: Props) {
  return (
    <>
      {title === "Overview" && (
        <>
          <div className="stats">
            {[
              [
                "Registered models",
                models.length,
                "Across three workload types",
                Box,
              ],
              [
                "Healthy models",
                models.filter((m) => health(m) === "HEALTHY").length,
                "Latest reliability evidence",
                ShieldCheck,
              ],
              [
                "Open incidents",
                incidents.filter((i) => i.status !== "RESOLVED").length,
                "Unresolved, across all versions",
                TriangleAlert,
              ],
              [
                "Active rollouts",
                deployments.filter((d) =>
                  ["CANARY", "PREPARING"].includes(d.status),
                ).length,
                "Observed before progression",
                GitBranch,
              ],
            ].map(([label, count, hint, Icon]: any) => (
              <div className="stat" key={label}>
                <div className="label">
                  {label}
                  <Icon size={15} />
                </div>
                <strong>{count}</strong>
                <small>{hint}</small>
              </div>
            ))}
          </div>
          {incidents.some((i) => i.status !== "RESOLVED") && (
            <div className="alert">
              <span>
                <TriangleAlert
                  size={14}
                  style={{ verticalAlign: "middle", marginRight: 8 }}
                />
                Unresolved reliability signals need review. Source failures can
                block retraining.
              </span>
              <Link href="/incidents">
                Inspect incidents <ArrowUpRight size={13} />
              </Link>
            </div>
          )}
          <Panel
            title="Model fleet"
            meta={`${models.length} workloads · latest evidence`}
          >
            <Table rows={models} columns={modelColumns} />
          </Panel>
          <div className="grid">
            <Panel title="Request throughput" meta="requests / second">
              <Trend
                series={metrics?.series?.requests_per_second}
                title="Request throughput"
              />
            </Panel>
            <Panel title="Recent activity" meta="Audit log">
              <div className="panel-body">
                <Timeline records={rows("audit").slice(0, 5)} />
              </div>
            </Panel>
          </div>
          <Panel
            title="Active incidents"
            meta={<Link href="/incidents">View all →</Link>}
          >
            <Table
              rows={incidents
                .filter((i) => i.status !== "RESOLVED")
                .slice(0, 6)}
              columns={incidentColumns}
            />
          </Panel>
        </>
      )}
      {title === "Models" && (
        <Panel
          title="Registered workloads"
          meta={
            <input
              aria-label="Filter models"
              className="filter"
              placeholder="Filter workloads…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          }
        >
          <Table
            rows={filtered(models)}
            columns={modelColumns}
            onSelect={setSelected}
          />
        </Panel>
      )}
      {title === "Incidents" && (
        <Panel
          title="Incident queue"
          meta={
            <input
              aria-label="Filter incidents"
              className="filter"
              placeholder="Filter severity, feature, state…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          }
        >
          <Table
            rows={filtered(incidents)}
            columns={incidentColumns}
            onSelect={setSelected}
          />
        </Panel>
      )}
      {title === "Deployments" && (
        <Panel
          title="Release history"
          meta="Start approved candidates from Governance"
        >
          <Table
            rows={deployments}
            onSelect={setSelected}
            columns={[
              [
                "Deployment",
                (r) => (
                  <>
                    <code>{short(r.id)}</code>
                    <span className="subline">{modelName(r.model_id)}</span>
                  </>
                ),
              ],
              [
                "Version",
                (r) =>
                  `v${version(r.previous_id)?.version} → v${version(r.candidate_id)?.version}`,
              ],
              ["Status", (r) => <Badge value={r.status} />],
              ["Candidate traffic", (r) => `${r.traffic_percent}%`],
              [
                "Health",
                (r) => <Badge value={r.health?.status || "AWAITING_TRAFFIC"} />,
              ],
              ["Started", (r) => date(r.started_at)],
            ]}
          />
        </Panel>
      )}
      {(title === "Pipelines" || title === "Governance") && (
        <>
          {!state.settings.airflow_configured && title === "Pipelines" && (
            <div className="alert">
              Airflow scheduling is not configured. Recorded requests and
              quality gates remain available.
            </div>
          )}
          <Panel
            title={
              title === "Governance"
                ? "Candidate decisions"
                : "Retraining requests"
            }
            meta="Select a request to inspect its evidence"
          >
            <Table
              rows={pipelines}
              onSelect={setSelected}
              columns={[
                [
                  "Request",
                  (r) => (
                    <>
                      <code>{short(r.id)}</code>
                      <span className="subline">{modelName(r.model_id)}</span>
                    </>
                  ),
                ],
                ["Algorithm", (r) => r.algorithm],
                ["State", (r) => <Badge value={r.status} />],
                [
                  "Gates",
                  (r) =>
                    r.results?.gates
                      ? `${r.results.gates.filter((g: any) => g.passed).length}/${r.results.gates.length} passed`
                      : "Not evaluated",
                ],
                ["Requested by", (r) => r.requested_by],
                ["Updated", (r) => date(r.updated_at)],
              ]}
            />
          </Panel>
        </>
      )}
      {title === "Datasets" && (
        <Panel
          title="Dataset versions"
          meta="SHA-256 addressed, immutable splits"
        >
          <Table
            rows={rows("dataset_versions")}
            onSelect={setSelected}
            columns={[
              [
                "Dataset",
                (r) => (
                  <>
                    {rows("datasets").find((d) => d.id === r.dataset_id)?.name}
                    <span className="subline mono">{short(r.fingerprint)}</span>
                  </>
                ),
              ],
              ["Source", (r) => r.manifest?.source],
              ["Train", (r) => r.manifest?.splits?.train?.rows],
              ["Validation", (r) => r.manifest?.splits?.validation?.rows],
              ["Test", (r) => r.manifest?.splits?.test?.rows],
              ["Created", (r) => date(r.created_at)],
            ]}
          />
        </Panel>
      )}
      {title === "Monitoring" && (
        <>
          {!metrics?.available && (
            <div className="alert">
              Prometheus is unavailable. Metrics are shown only when returned by
              the monitoring backend.
            </div>
          )}
          <div className="grid">
            {[
              ["requests_per_second", "Request throughput · req/s"],
              ["p95_seconds", "p95 HTTP latency · seconds"],
              ["error_ratio", "HTTP server error ratio"],
            ].map(([key, label]) => (
              <Panel key={key} title={label} meta="Past 30 minutes">
                <Trend series={metrics?.series?.[key]} title={label} />
              </Panel>
            ))}
          </div>
          <Panel
            title="Rollout health"
            meta={`${state.routing_count} recorded routed requests`}
          >
            <Table
              rows={deployments}
              columns={[
                ["Model", (r) => modelName(r.model_id)],
                [
                  "Health",
                  (r) => (
                    <Badge value={r.health?.status || "AWAITING_TRAFFIC"} />
                  ),
                ],
                ["Samples", (r) => text(r.health?.requests)],
                ["p95 ms", (r) => text(r.health?.p95_ms)],
                ["Errors", (r) => text(r.health?.error_rate)],
                ["Evaluated", (r) => date(r.health?.evaluated_at)],
              ]}
            />
          </Panel>
        </>
      )}
      {title === "Audit" && (
        <Panel
          title="Audit trail"
          meta={
            <input
              aria-label="Filter audit events"
              className="filter"
              placeholder="Filter actor or operation…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          }
        >
          <Table
            rows={filtered(rows("audit"))}
            onSelect={setSelected}
            columns={[
              ["Event", (r) => <code>{short(r.id)}</code>],
              ["Operation", (r) => r.action],
              ["Actor", (r) => r.actor],
              [
                "Resource",
                (r) => (
                  <code>
                    {r.resource_type}/{short(r.resource_id)}
                  </code>
                ),
              ],
              ["Time", (r) => date(r.timestamp)],
            ]}
          />
        </Panel>
      )}
      {title === "Settings" && (
        <div className="detail-grid">
          <Panel title="Workspace configuration">
            <div className="panel-body">
              <dl>
                {[
                  ["Environment", state.environment],
                  ["Runtime", state.settings.backend],
                  ["Identity", state.settings.identity],
                  [
                    "API writes",
                    state.settings.mutation_enabled
                      ? "Operator token configured"
                      : "Read-only",
                  ],
                  [
                    "Controller",
                    state.settings.controller_enabled
                      ? "Running in control API"
                      : "Disabled",
                  ],
                  [
                    "Airflow",
                    state.settings.airflow_configured
                      ? "Configured"
                      : "Unavailable",
                  ],
                ].map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
              <p className="footer-note">
                This workspace uses local development identity. Operator
                credentials stay on the server. Policy edits are made through
                reviewed configuration files.
              </p>
            </div>
          </Panel>
          <Panel
            title="Automation policy"
            meta={`Level ${state.settings.policy.autonomy_level}`}
          >
            <div className="panel-body">
              <dl>
                {Object.entries(state.settings.policy).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k.replaceAll("_", " ")}</dt>
                    <dd className="mono">{text(v)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </Panel>
        </div>
      )}
    </>
  );
}
