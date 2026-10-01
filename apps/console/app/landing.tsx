"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  Copy,
  Database,
  GitBranch,
  Layers,
  LockKeyhole,
  Network,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import "./landing.css";

const stages = [
  {
    number: "01",
    label: "Observe",
    title: "Find the signal\nin the noise.",
    body: "Follow feature drift, data quality, model performance, and serving health. Every signal comes from measured evidence.",
    icon: Activity,
    code: "MONITOR → DETECT",
    color: "#b5ecc9",
  },
  {
    number: "02",
    label: "Understand",
    title: "Investigate first.\nAct with context.",
    body: "Separate model degradation from an upstream data failure. Trace an incident to its evidence before choosing what happens next.",
    icon: Network,
    code: "INVESTIGATE → CLASSIFY",
    color: "#b6c9ff",
  },
  {
    number: "03",
    label: "Improve",
    title: "Better models.\nProven, not presumed.",
    body: "Run reproducible training, compare candidates on common data, and enforce quality gates before an explicit approval.",
    icon: Workflow,
    code: "RETRAIN → VALIDATE",
    color: "#f2c7a5",
  },
  {
    number: "04",
    label: "Release",
    title: "Move forward.\nKeep a way back.",
    body: "Introduce a candidate at 10%, observe real traffic, and progress only with healthy evidence. Restore the previous version when health fails.",
    icon: GitBranch,
    code: "CANARY → PROMOTE / ROLLBACK",
    color: "#c4b9fa",
  },
];
export default function Landing() {
  const flow = useRef<HTMLElement>(null),
    scene = useRef<HTMLDivElement>(null),
    [stage, setStage] = useState(0),
    [copied, setCopied] = useState("");
  useEffect(() => {
    let frame = 0,
      current = 0,
      target = 0,
      lastStage = -1;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    const measure = () => {
      if (!flow.current) return;
      const rect = flow.current.getBoundingClientRect();
      target = Math.max(
        0,
        Math.min(
          1,
          -rect.top / (flow.current.offsetHeight - window.innerHeight),
        ),
      );
      if (!frame) frame = requestAnimationFrame(draw);
    };
    const draw = () => {
      current = reduce.matches ? target : current + (target - current) * 0.09;
      if (Math.abs(target - current) < 0.0002) current = target;
      scene.current?.style.setProperty("--flow", String(current));
      const next = Math.min(3, Math.floor(current * 4));
      if (next !== lastStage) {
        setStage(next);
        lastStage = next;
      }
      frame =
        Math.abs(target - current) > 0.0002 ? requestAnimationFrame(draw) : 0;
    };
    window.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure);
    measure();
    return () => {
      window.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
      cancelAnimationFrame(frame);
    };
  }, []);
  async function copy(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      setTimeout(() => setCopied(""), 2000);
    } catch {
      setCopied("Select and copy the visible value");
    }
  }
  const current = stages[stage],
    Icon = current.icon;
  return (
    <div className="atlas-site">
      <a className="skip" href="#platform">
        Skip to platform details
      </a>
      <header className="site-header">
        <Link href="/" className="atlas-wordmark">
          <span className="atlas-symbol">A</span>ATLAS
        </Link>
        <nav aria-label="Platform navigation">
          <a href="#platform">Platform</a>
          <a href="#workloads">Workloads</a>
          <a href="#access">Demo access</a>
        </nav>
        <Link className="site-nav-login" href="/login">
          Open workspace
          <ArrowUpRight size={15} />
        </Link>
      </header>
      <main>
        <section className="site-hero">
          <div className="hero-topline">
            <span className="site-kicker">
              <i />
              AUTONOMOUS ML RELIABILITY & OPERATIONS
            </span>
            <span className="site-coordinate">
              LOCAL / OPEN SOURCE / EVIDENCE FIRST
            </span>
          </div>
          <div className="hero-columns">
            <div>
              <h1>
                Every model.
                <br />
                <em>Under control.</em>
              </h1>
              <p>
                Model intelligence doesn’t end at deployment.
                <br />
                Meet the operations layer that keeps it reliable.
              </p>
              <div className="hero-actions">
                <Link className="site-button" href="/login">
                  Enter ATLAS
                  <ArrowUpRight size={19} />
                </Link>
                <a className="site-text-link" href="#platform">
                  Follow the lifecycle
                  <ArrowDown size={15} />
                </a>
              </div>
            </div>
            <div
              className="hero-diagram"
              aria-label="ATLAS connects data, models and infrastructure"
            >
              <div className="hero-grid" />
              <div className="hero-axis x" />
              <div className="hero-axis y" />
              <div className="hero-pillar one">
                <span>DATA</span>
              </div>
              <div className="hero-pillar two">
                <span>MODELS</span>
              </div>
              <div className="hero-pillar three">
                <span>INFRASTRUCTURE</span>
              </div>
              <div className="hero-floor-label">ATLAS / CONTROL PLANE</div>
              <span className="diagram-corner top">SYSTEM ARCHITECTURE</span>
              <span className="diagram-corner bottom">
                THREE WORKLOADS. ONE SHARED PLATFORM.
              </span>
            </div>
          </div>
          <div className="hero-bottom">
            <span>
              <Layers size={15} />
              From model signal to safe release
            </span>
            <a href="#platform">
              SCROLL TO EXPLORE <ArrowDown size={13} />
            </a>
            <span className="mono">01 — 04</span>
          </div>
        </section>
        <section id="platform" className="flow-section" ref={flow}>
          <div className="flow-sticky">
            <div className="flow-top">
              <span className="site-kicker">THE ATLAS LIFECYCLE</span>
              <span className="site-coordinate">
                SCROLL-DRIVEN SYSTEM EXPLORER
              </span>
            </div>
            <div className="flow-layout">
              <div className="flow-copy">
                <span className="flow-number">
                  {current.number}
                  <span>/ 04</span>
                </span>
                <div className="flow-label">
                  <Icon size={15} />
                  {current.label}
                </div>
                <h2>
                  {current.title.split("\n").map((line, i) => (
                    <span key={line}>
                      {line}
                      {i === 0 && <br />}
                    </span>
                  ))}
                </h2>
                <p>{current.body}</p>
                <code>{current.code}</code>
                <a href="#workloads" className="flow-skip">
                  Skip animation
                  <ArrowDown size={13} />
                </a>
              </div>
              <div
                className="scene-wrap"
                ref={scene}
                style={
                  {
                    "--flow": 0,
                    "--stage-color": current.color,
                  } as React.CSSProperties
                }
              >
                <div className="scene-grid" />
                <div className="scene-halo" />
                <div className="scene-3d">
                  <div className="orbital-ring ring-a" />
                  <div className="orbital-ring ring-b" />
                  <div className="orbital-ring ring-c" />
                  <div className="core-cube">
                    <div className="cube-face front">
                      <span className="atlas-symbol">A</span>
                      <strong>ATLAS</strong>
                      <small>RELIABILITY CORE</small>
                    </div>
                    <div className="cube-face back" />
                    <div className="cube-face left" />
                    <div className="cube-face right" />
                    <div className="cube-face top" />
                    <div className="cube-face bottom" />
                  </div>
                  {stages.map((s, i) => (
                    <div
                      key={s.label}
                      className={`system-node node-${i} ${stage === i ? "node-active" : ""}`}
                    >
                      <s.icon size={19} />
                      <span>{s.label.toUpperCase()}</span>
                      <small>{s.number}</small>
                    </div>
                  ))}
                  <div className="data-plane plane-one" />
                  <div className="data-plane plane-two" />
                  <div className="orbit-particle" />
                </div>
                <div className="scene-caption">
                  <span>
                    <i />
                    LIFECYCLE ILLUSTRATION
                  </span>
                  <span className="mono">{current.code}</span>
                </div>
                <div className="scene-scale">
                  <span>INPUT</span>
                  <div />
                  <span>OUTCOME</span>
                </div>
              </div>
            </div>
            <div className="flow-progress">
              {stages.map((s, i) => (
                <div
                  key={s.label}
                  className={
                    i === stage ? "active" : i < stage ? "complete" : ""
                  }
                >
                  <span>{s.number}</span>
                  {s.label}
                  <div className="progress-track">
                    <i />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
        <section className="workload-section" id="workloads">
          <div className="section-heading">
            <div>
              <span className="site-kicker">
                ONE PLATFORM. DIFFERENT FAILURE MODES.
              </span>
              <h2>
                Reliability has
                <br />
                more than one shape.
              </h2>
            </div>
            <p>
              Three reproducible workloads put the same governance,
              investigation, and remediation services to work.
            </p>
          </div>
          <div className="workload-grid">
            {[
              {
                name: "Fraud detection",
                type: "CLASSIFICATION",
                icon: ShieldCheck,
                number: "01",
                text: "Catch changing transaction patterns. Measure precision, recall, and the cost of missed signals.",
                signal: "BEHAVIOR SHIFT → MODEL INVESTIGATION",
              },
              {
                name: "Predictive maintenance",
                type: "SENSOR RELIABILITY",
                icon: Activity,
                number: "02",
                text: "Spot corrupted sensor readings before they become bad training data. Fix the source, not the wrong model.",
                signal: "SENSOR FAILURE → UPSTREAM INVESTIGATION",
              },
              {
                name: "Energy forecasting",
                type: "TIME-SERIES REGRESSION",
                icon: GitBranch,
                number: "03",
                text: "Follow changing demand patterns through forecast error, feature drift, and chronological evaluation.",
                signal: "DEMAND SHIFT → VALIDATED RETRAINING",
              },
            ].map((w) => (
              <article key={w.number}>
                <div className="workload-top">
                  <w.icon size={23} />
                  <span>{w.number}</span>
                </div>
                <small>{w.type}</small>
                <h3>{w.name}</h3>
                <p>{w.text}</p>
                <code>{w.signal}</code>
              </article>
            ))}
          </div>
        </section>
        <section className="principles">
          <div>
            <span className="site-kicker">BUILT TO BE ACCOUNTABLE</span>
            <h2>
              Evidence at every step.
              <br />A record of every decision.
            </h2>
          </div>
          <div className="principle-list">
            {[
              [
                "01",
                "Measured, not manufactured",
                "Live service telemetry, immutable datasets, and versioned model artifacts.",
              ],
              [
                "02",
                "Governed by policy",
                "Fresh validation, quality thresholds, and explicit candidate approval.",
              ],
              [
                "03",
                "Designed for recovery",
                "Progressive traffic, retained versions, and auditable rollback.",
              ],
            ].map(([n, t, b]) => (
              <div key={n}>
                <code>{n}</code>
                <span>
                  <h3>{t}</h3>
                  <p>{b}</p>
                </span>
                <ArrowUpRight size={18} />
              </div>
            ))}
          </div>
        </section>
        <section id="access" className="access-section">
          <div className="access-intro">
            <span className="site-kicker">YOUR LOCAL WORKSPACE</span>
            <h2>
              Step inside
              <br />
              the control plane.
            </h2>
            <p>
              Explore the real models, incident evidence, retraining gates, and
              deployment history in this development environment.
            </p>
            <Link className="site-button" href="/login">
              Open login
              <ArrowRight size={18} />
            </Link>
            <span className="access-caption">
              <LockKeyhole size={13} />
              Public demo credentials · local development only
            </span>
          </div>
          <div className="credentials-panel">
            <div className="credentials-head">
              <span>
                <i />
                DEVELOPMENT ACCESS
              </span>
              <span>ATLAS / LOCAL</span>
            </div>
            <div className="credential-main">
              <div>
                <span>ATLAS CONSOLE</span>
                <small>http://127.0.0.1:3100/login</small>
              </div>
              <div className="credential-fields">
                {[
                  ["Username", "atlas"],
                  ["Password", "atlas_local"],
                ].map(([label, value]) => (
                  <div key={label}>
                    <small>{label}</small>
                    <code>{value}</code>
                    <button
                      aria-label={`Copy ATLAS ${label.toLowerCase()}`}
                      onClick={() => copy(value, label)}
                    >
                      {copied === label ? (
                        <Check size={15} />
                      ) : (
                        <Copy size={15} />
                      )}
                    </button>
                  </div>
                ))}
              </div>
            </div>
            <div className="service-credentials">
              <div>
                <strong>Grafana</strong>
                <span>Port 3000</span>
                <code>aegis / aegis_local</code>
              </div>
              <div>
                <strong>PostgreSQL</strong>
                <span>Native port 55432 · database aegis</span>
                <code>aegis / aegis_local</code>
              </div>
              <div>
                <strong>MLflow</strong>
                <span>Native port 55000</span>
                <code>No login in local mode</code>
              </div>
              <div>
                <strong>Prometheus</strong>
                <span>Port 9090</span>
                <code>No login in local mode</code>
              </div>
              <div>
                <strong>Airflow</strong>
                <span>Optional Docker service · port 8080</span>
                <code>aegis / generated at startup</code>
              </div>
            </div>
            <p className="credential-note">
              Airflow generates its password in the local service logs. Existing
              infrastructure retains its original development usernames.
              Operator API tokens remain server-managed.
            </p>
            <span className="copy-status" role="status">
              {copied ? `Copied: ${copied}` : ""}
            </span>
          </div>
        </section>
      </main>
      <footer className="site-footer">
        <Link href="/" className="atlas-wordmark">
          <span className="atlas-symbol">A</span>ATLAS
        </Link>
        <p>Autonomous ML Reliability & Operations Platform</p>
        <span>LOCAL FIRST. EVIDENCE ALWAYS.</span>
        <a
          href="#top"
          aria-label="Back to top"
          onClick={(e) => {
            e.preventDefault();
            window.scrollTo({
              top: 0,
              behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
                .matches
                ? "instant"
                : "smooth",
            });
          }}
        >
          <ArrowUpRight size={19} />
        </a>
      </footer>
    </div>
  );
}
