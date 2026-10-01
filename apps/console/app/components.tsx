"use client";
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

// JSON records retain complete backend evidence; the presentation names each domain field.
export type Row = { id: string; [key: string]: any };
export type State = {
  generated_at: string;
  environment: string;
  settings: Record<string, any>;
  routing_count: number;
  [key: string]: any;
};
export type Action = {
  title: string;
  path: string;
  extra?: Record<string, unknown>;
};
export const navigation = [
  ["Overview", LayoutDashboard],
  ["Models", Box],
  ["Deployments", GitBranch],
  ["Incidents", TriangleAlert],
  ["Datasets", Database],
  ["Pipelines", Workflow],
  ["Monitoring", Activity],
  ["Governance", ShieldCheck],
  ["Audit", ListChecks],
  ["Settings", Settings],
] as const;
export const short = (value: unknown) => String(value ?? "—").slice(0, 8);
export const date = (value: unknown) =>
  value
    ? new Date(String(value)).toLocaleString(undefined, {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
export const text = (value: unknown) =>
  value == null
    ? "—"
    : typeof value === "number"
      ? Number.isInteger(value)
        ? String(value)
        : value.toFixed(4)
      : String(value);
export function Badge({ value }: { value: unknown }) {
  const v = String(value || "UNASSESSED");
  const tone = [
    "HEALTHY",
    "APPROVED",
    "PROMOTED",
    "FINISHED",
    "champion",
    "ACCEPTED",
    "PASSED",
  ].includes(v)
    ? "good"
    : /CRITICAL|REJECTED|FAILED|UNHEALTHY/.test(v)
      ? "bad"
      : /HIGH|WARNING|AWAITING|ROLLED_BACK/.test(v)
        ? "warn"
        : "info";
  return (
    <span className={`badge ${tone}`}>
      <i className="dot" />
      {v.replaceAll("_", " ")}
    </span>
  );
}
export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="empty">
      <Layers size={22} />
      {children}
    </div>
  );
}
export function Panel({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        <small>{meta}</small>
      </div>
      {children}
    </section>
  );
}
export function Evidence({ value }: { value: unknown }) {
  return (
    <details>
      <summary>Inspect recorded evidence</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function Table({
  columns,
  rows,
  onSelect,
}: {
  columns: [string, (r: Row) => React.ReactNode][];
  rows: Row[];
  onSelect?: (r: Row) => void;
}) {
  return rows.length ? (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {columns.map(([label]) => (
              <th key={label}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              {columns.map(([label, render], i) => (
                <td key={label}>
                  {i === 0 && onSelect ? (
                    <button className="row-link" onClick={() => onSelect(r)}>
                      {render(r)}
                    </button>
                  ) : (
                    render(r)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty>
      No records match this view. New activity will appear automatically.
    </Empty>
  );
}
export function Trend({
  series,
  title,
}: {
  series: any[] | undefined;
  title: string;
}) {
  const points = (series?.[0]?.values || [])
    .filter((p: any[]) => Number.isFinite(Number(p[1])))
    .map((p: any[]) => Number(p[1]));
  if (!points.length)
    return <Empty>No samples available for {title.toLowerCase()}.</Empty>;
  const min = Math.min(...points),
    max = Math.max(...points),
    range = max - min || 1;
  const path = points
    .map(
      (v: number, i: number) =>
        `${i ? "L" : "M"}${(i * 560) / Math.max(points.length - 1, 1)},${125 - ((v - min) / range) * 110}`,
    )
    .join(" ");
  return (
    <div className="panel-body">
      <div className="status-line">
        <strong className="mono">{points.at(-1)?.toFixed(3)}</strong>
        <small>latest observed value</small>
      </div>
      <div className="chart">
        <svg
          role="img"
          aria-label={`${title}: ${points.length} real samples, minimum ${min.toFixed(3)}, maximum ${max.toFixed(3)}`}
          viewBox="0 0 560 150"
          preserveAspectRatio="none"
        >
          <line x1="0" x2="560" y1="40" y2="40" />
          <line x1="0" x2="560" y1="90" y2="90" />
          <line x1="0" x2="560" y1="140" y2="140" />
          <path d={path} />
        </svg>
      </div>
      <div className="chart-labels">
        <span>30 minutes ago</span>
        <span>Prometheus · 30s resolution</span>
        <span>Now</span>
      </div>
    </div>
  );
}

export function Timeline({ records }: { records: Row[] }) {
  return records.length ? (
    <ol className="timeline">
      {records.slice(0, 12).map((r) => (
        <li key={r.id}>
          {r.action.replaceAll(".", " / ")}
          <small>
            {r.actor} · {date(r.timestamp)}
          </small>
        </li>
      ))}
    </ol>
  ) : (
    <Empty>No recorded activity yet.</Empty>
  );
}
