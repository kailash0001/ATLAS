"use client";
import Link from "next/link";
import { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Eye,
  EyeOff,
  LockKeyhole,
  Layers,
} from "lucide-react";
import "../landing.css";
export default function Login() {
  const [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [show, setShow] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail);
      window.location.assign("/overview");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <main className="atlas-site login-shell">
      <section className="login-story">
        <Link href="/" className="atlas-wordmark">
          <span className="atlas-symbol">A</span>ATLAS
          <span className="atlas-wordmark-tag">ML OPERATIONS</span>
        </Link>
        <div className="login-story-content">
          <span className="site-kicker">THE RELIABILITY WORKSPACE</span>
          <h1>
            Your models.
            <br />
            Your evidence.
            <br />
            <em>Your next move.</em>
          </h1>
          <p>
            One control plane to follow every model from its first signal to its
            next safe release.
          </p>
          <div className="login-orbit" aria-hidden="true">
            <div className="login-orbit-ring" />
            <div className="login-orbit-ring second" />
            <div className="login-orbit-core">
              <Layers size={45} />
            </div>
            <span>MONITOR</span>
            <span>UNDERSTAND</span>
            <span>DEPLOY</span>
          </div>
        </div>
        <div className="login-story-footer">
          LOCAL FIRST <span>OPEN SOURCE</span>
          <span>BUILT FOR EVIDENCE</span>
        </div>
      </section>
      <section className="login-form-side">
        <Link className="site-back" href="/">
          <ArrowLeft size={15} />
          Back to platform
        </Link>
        <div className="login-form-wrap">
          <div className="login-icon">
            <LockKeyhole size={22} />
          </div>
          <span className="site-kicker">ATLAS / WORKSPACE ACCESS</span>
          <h2>Welcome back.</h2>
          <p className="login-description">
            Sign in to your local operations workspace.
          </p>
          <form onSubmit={submit}>
            <label htmlFor="username">Username</label>
            <input
              id="username"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter your username"
              autoFocus
            />
            <label htmlFor="password">Password</label>
            <div className="password-field">
              <input
                id="password"
                type={show ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
              />
              <button
                type="button"
                aria-label={show ? "Hide password" : "Show password"}
                onClick={() => setShow(!show)}
              >
                {show ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            {error && (
              <p role="alert" className="login-error">
                {error}
              </p>
            )}
            <button className="site-button login-submit" disabled={busy}>
              {busy ? "Opening workspace…" : "Enter workspace"}
              <ArrowRight size={17} />
            </button>
          </form>
          <div className="login-demo">
            <span className="site-kicker">LOCAL DEMO ACCOUNT</span>
            <div>
              <span>
                Username <code>atlas</code>
              </span>
              <span>
                Password <code>atlas_local</code>
              </span>
            </div>
            <button
              onClick={() => {
                setUsername("atlas");
                setPassword("atlas_local");
              }}
            >
              Use demo credentials <ArrowUp />
            </button>
          </div>
          <p className="login-note">
            Demo access is shared intentionally. Sessions expire after eight
            hours; platform operations still require policy checks.
          </p>
        </div>
        <footer>ATLAS · Autonomous ML Reliability & Operations</footer>
      </section>
    </main>
  );
}
function ArrowUp() {
  return <ArrowRight size={13} />;
}
