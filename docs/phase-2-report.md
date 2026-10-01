# Phase 2 implementation and verification

Phase 2 adds actual serving and observability to the existing Phase 1 foundation.
The registered fraud model, training services, lineage and governance were preserved.
Work stays within Phase 2: no custom console, incident engine, Airflow or Kubernetes.

## Files and architecture

| Area | Added or updated |
| --- | --- |
| HTTP application | `apps/inference/main.py`, `apps/inference/middleware.py`, package initializers |
| Serving domain | `aegis/serving/{config,errors,schemas,loader,service,metrics}.py` |
| Persistence | `aegis/db/models.py`, migration `0002_prediction_events_and_delayed_labels.py` |
| Structured logs | `aegis/core/logging.py` now preserves structured request/model context |
| Dependencies | `pyproject.toml`, `requirements.lock` add pinned API/metrics/HTTP dependencies |
| Containers | Inference Dockerfile; optional Compose serving, Prometheus and Grafana services |
| Monitoring | Native/container Prometheus configs, Grafana datasource/dashboard provisioning, 14-panel dashboard JSON |
| Local execution | `scripts/install_monitoring.py`, `native_observability.py`, `traffic.py`, `verify_phase2.py`, `build_dashboard.py`; task runner and Make targets |
| Existing native setup | Preserves additional `.env` settings when native service endpoints match |
| Tests | Serving unit tests, real MLflow-to-HTTP lifecycle, PostgreSQL concurrent-label tests |
| Documentation | README, architecture, monitoring, serving, deployment, local setup, demo and this report |

Flow: client → FastAPI validation/correlation → governed immutable MLflow artifact →
full preprocessing/model prediction → durable PostgreSQL event → response. Delayed
actual labels join by prediction ID. Prometheus scrapes actual HTTP/process/model
metrics; Grafana queries Prometheus. Read-only model/summary API routes expose real
state for the future control plane.

## Database changes

Migration `0002` adds `prediction_events` with event ID, request ID, model-version FK,
creation time, allowlisted raw features, probability, class, threshold, inference time,
and optional actual label/labeled time. Constraints enforce probability/class/label
validity. Indexes support version/time-window and correlation queries.

Existing tables/data are retained. Labels update the event under a row lock and create
one audit event. Same-label retries are idempotent; conflicting labels return 409.
Prometheus time-series samples are not duplicated into PostgreSQL.

## Running locally

Current services use the isolated native stack because this host's Docker engine is
unavailable. State remains under `.local`; binaries are official, checksum-verified
Prometheus 3.14.0 and Grafana OSS 13.2.2 releases.

- [API docs](http://127.0.0.1:8000/docs)
- [Prometheus](http://127.0.0.1:9090)
- [Grafana dashboard](http://127.0.0.1:3000/d/aegis-fraud-serving)
- Grafana login: `aegis` / `aegis_local` (local development).
- Existing MLflow: localhost:55000; PostgreSQL: localhost:55432.
- Served model: `fraud-detector-development`, version 3.

From the repository root after installing the updated project:

```powershell
.\.venv\Scripts\python.exe scripts/native_infra.py up
.\.venv\Scripts\aegis.exe db upgrade
.\.venv\Scripts\python.exe scripts/install_monitoring.py
.\.venv\Scripts\python.exe scripts/native_observability.py up
.\.venv\Scripts\python.exe scripts/traffic.py --count 300 --rate 15 --concurrency 8 --labels --invalid-every 20
.\.venv\Scripts\python.exe scripts/verify_phase2.py
```

Existing trained models need not be retrained. A fresh checkout must train/promote
one candidate before starting inference. Compose users instead prepare Phase 1 in
Compose mode and run `python scripts/dev.py serving-up`. See [deployment](deployment.md).

## Verification executed

**36 tests passed, 0 failed, 0 skipped; 89% statement coverage across `aegis` and `apps`.**
Serving service coverage is 97%, loader 89%, metrics 94%, and the HTTP adapter 87%.

```powershell
$env:AEGIS_TEST_POSTGRES_URL='postgresql+psycopg://aegis:aegis_local@127.0.0.1:55432/aegis'
.\.venv\Scripts\python.exe -m pytest --cov=aegis --cov=apps --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
docker compose --profile serving config --quiet
```

The official `promtool check config` passed for both scrape configurations. Tests cover
real MLflow artifact loading and HTTP predictions, stored threshold use, schema failures,
missing/unknown features, event durability, label idempotency/conflicts, concurrent
PostgreSQL labeling, readiness changes, bounded payloads/labels, overload, inference/write
failures, durable metric windows and Phase 1 regressions. PostgreSQL migration round-trip
and schema drift checks passed in disposable databases.

Live verification passed against the running processes:

- Governed champion version 3 loaded successfully.
- Prometheus target up; model metrics equal the database-backed API summary.
- Grafana datasource health OK and datasource proxy retrieves actual Prometheus values.
- All 26 PromQL expressions accepted; all 14 provisioned dashboard panels present.
- Native services restarted after an interrupted session with stored data intact.
- Observations older than one hour correctly left the current window; verification
  required new traffic rather than treating old evidence as current.

The refreshed measured traffic run sent 300 requests at 15 requests/second with eight
client workers: **285 HTTP 200, 15 expected HTTP 422, no HTTP 5xx; 285 labels persisted**.
Client-observed latencies were p50 **17.99 ms**, p95 **21.60 ms**, p99 **24.85 ms**.
These are one local smoke/load sample, not a production capacity guarantee.

The labeled confusion matrix was TP=0, FP=3, FN=15, TN=267, yielding precision/recall/F1
of zero and false-positive rate 0.01111. These are actual measured outcomes from the
synthetic baseline. Healthy APIs do not imply a useful fraud model; poor model quality
remains visible. The champion designation is still development-only.

## Limitations

- Docker configuration was validated; container image build/runtime was not executable
  on this host. Actual services were verified through the native path.
- Local-only, single-worker serving; no authentication/TLS, distributed metrics or
  automatic reload/rollout. Uvicorn transport failures can precede app telemetry.
- Prediction requests are not idempotent; delayed-label writes are. Label sources are
  trusted local inputs. Corrections need a future governed workflow.
- Raw allowlisted feature events are retained without automatic pruning/partitioning.
- Metrics are scoped to a configurable prediction-time window and loaded model version.
  Missing or biased ground truth limits performance interpretation.
- Model execution is in-process; external I/O is bounded but inference has no hard
  cancellation deadline. Tests include dependency deprecation/schema warnings.
- Drift, incident severity/root-cause analysis and retraining are not implemented here.

## Phase 3 entry point

Add reference/current comparisons, data-quality/drift evidence, normalized severity and
first-class incidents over these real events and dataset manifests. Introduce predictive
maintenance and controlled sensor corruption. Distinguish upstream data failures from
model degradation before recommending remediation. See [deployment](deployment.md).
