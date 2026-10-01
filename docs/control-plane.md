# ATLAS control plane

ATLAS is the platform name. Existing `aegis` Python modules, database usernames,
MLflow registry names and environment variables remain compatible with earlier phases.

## Start the local workspace

Start native infrastructure, apply migrations, then build and run the console:

```powershell
.\.venv\Scripts\python.exe scripts/native_infra.py up
.\.venv\Scripts\aegis.exe db upgrade
cd apps/console
npm ci
npm run build
cd ../..
.\.venv\Scripts\python.exe scripts/native_console.py up
```

Open http://127.0.0.1:3100. Sign in with **atlas / atlas_local**.
The landing page includes the demo account and local service credentials. PostgreSQL
uses `aegis / aegis_local` on native port 55432; Grafana uses the same credentials on
3000. MLflow (55000) and Prometheus (9090) have no local login. Optional Airflow (8080)
generates its password at startup; see its service logs rather than inventing one.

The front page uses a CSS 3D architecture illustration and a scroll-driven lifecycle:
Observe, Understand, Improve, Release. Animation uses requestAnimationFrame with
smoothed progress, preserves native scrolling, offers a skip link, and honors reduced
motion. The scene is labeled as an illustration; it is not simulated telemetry.

Login issues an HMAC-signed, eight-hour HttpOnly SameSite=Strict cookie. Secure is set
on HTTPS. This is an intentionally shared local demo account, not production identity
management. The native launcher generates an ignored operator token in `.local`;
the browser never receives that token. Mutation requests also validate origin and
backend governance policies. An optional `ATLAS_SESSION_SECRET` separates session
signing from the operator token.

## Workspaces

- Overview: model fleet, recorded health, open incidents, real throughput and audit.
- Models: registered versions, metrics, dataset lineage and model details.
- Deployments: traffic stages, health evidence, progression and rollback controls.
- Incidents: persistent signals, investigation, acknowledgement and resolution.
- Datasets: immutable dataset versions, fingerprints and manifests.
- Pipelines: retraining requests, stages, gate results and optional Airflow dispatch.
- Monitoring: Prometheus range queries and recorded rollout health.
- Governance: candidate review, explicit decisions and deployment eligibility.
- Audit: persisted operator and automation actions.
- Settings: environment, integration availability and reviewed rollout policy.

The console refreshes database state every ten seconds and telemetry every thirty.
Collections show up to 100 recent rows. Unavailable telemetry is shown as unavailable.
The command palette supports Ctrl+K. Tables scroll on narrow screens.

Control API listens on localhost:8100. Restart after source changes with
`python scripts/native_console.py down` then `up`; build the frontend first.
The helper verifies process identity before stopping its own process trees.

For kind, the backend is separately reachable at localhost:18100. To connect a
manually started console, set `AEGIS_CONTROL_URL=http://127.0.0.1:18100` and supply
the corresponding `.local/kind-control-token` through `AEGIS_CONTROL_TOKEN`.
Native and kind databases and artifacts are separate environments.
