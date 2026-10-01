# Phase 4 implementation and verification

Implemented incident intelligence and the energy-demand forecasting workload.
Deterministic rules establish cited findings and likely categories before any optional
local AI step. No investigation component can execute retraining, deployment or rollback.

## Delivered changes

- `aegis/investigation/service.py`: collects report evidence, model/run/dataset
  lineage, policies, profiles, metrics and incident history into persistent snapshots.
  Facts include report IDs and JSON pointers. Hourly errors produce a measured
  afternoon error-share fact.
- `rules.py`: versioned deterministic precedence across UPSTREAM_SYSTEM, DEPLOYMENT,
  INFRASTRUCTURE, DATA, MODEL and UNKNOWN, supporting fact IDs, contributing categories,
  next-step codes and an explicit no-action conclusion. Data-quality failure overrides
  model degradation and vetoes retraining recommendations.
- `local_ai.py`: optional Ollama loopback adapter with bounded structured output.
  Only existing fact IDs and permitted next-step IDs are accepted. The deterministic
  renderer supplies prose and metric values; model text cannot invent a metric or
  change a rule conclusion. Attempts are audited separately as ACCEPTED, REJECTED or
  UNAVAILABLE, preserving the original investigation.
- Migration `0004`: `investigations` and `investigation_explanations`, foreign keys,
  category/status constraints and unique investigation fingerprints. Concurrent
  requests deduplicate under PostgreSQL incident locks.
- `aegis/data/energy.py`, `configs/models/energy.yaml`: reproducible hourly demand,
  one-hour issue/target contract, causal 24-hour lag, chronological splits, Ridge and
  RandomForestRegressor baselines, and controlled fault batches.
- Regression support in shared training, registry comparison and reliability:
  MAE, RMSE, MAPE percentage, explicit near-zero-target coverage, per-hour error
  statistics, forecast-distribution drift and policy-driven MAPE degradation.
- `aegis energy forecast/inject` and `aegis investigations run/list/show/export/explain-local`;
  `scripts/verify_phase4.py`, task-runner targets, tests and operating documentation.
- Serving schema expectation advanced to `0004`; binary fraud/maintenance serving
  remains compatible. Energy operates as timestamped forecast batches in this phase.

## Actual local results

Registered two candidates in `energy-demand-development`, without promotion:

| Version | Estimator | Validation MAPE | Test MAPE | Test MAE (kW) |
| --- | --- | --- | --- | --- |
| 1 | Ridge | 3.4962% | 3.4848% | 2.8036 |
| 2 | Random forest | 3.1373% | 3.1375% | 2.5325 |

The 12,000 synthetic hourly observations split into 7,200 training, 2,400 validation
and 2,400 test rows. Metrics were computed from real fitted artifacts, not hard-coded
dashboard values. These results do not establish accuracy on real utility data.

Four persisted v2 evaluation scenarios produced:

| Scenario | Health | MAPE | Investigation category |
| --- | --- | --- | --- |
| Clean held-out readings | HEALTHY | 3.1375% | No incident |
| Occupancy shift | HIGH | 10.9244% | DATA, with MODEL contributing |
| Changed demand relationship | HIGH | 11.8892% | MODEL |
| Corrupted source inputs | CRITICAL | Unavailable; scoring skipped | UPSTREAM_SYSTEM |

For occupancy shift, 500 outcomes in hours 14–18 UTC accounted for **91.9131%** of
total absolute forecast error. Temperature was not marked drifted. CPU, latency and
deployment evidence were explicitly unavailable, not described as normal. Corrupted
source inputs disabled retraining eligibility. All conclusions retained
`automatic_action: NONE`.

Review artifacts are under `data/investigations/phase4-demo/`: scenario CSVs,
`forecasts.csv`, `results.json`, investigation JSON bundles and text explanations.
The data directory is ignored by Git; source, policies, scripts and docs are retained.

## Verification

**74 tests passed, 0 skipped; 90% coverage** across `aegis` and `apps`.

The suite exercised all three real MLflow workloads; chronological/disjoint energy
splits and causal lag alignment; two regression estimators; forecast CSV generation
without target labels; lower-is-better candidate ranking; actual fault evidence;
zero-target MAPE handling; timestamp contract failures; persisted citations and
idempotency; source-quality precedence; all root-cause categories; invalid local-AI
IDs/actions/metrics; offline fallback; PostgreSQL migration roundtrips/schema checks;
and concurrent investigation deduplication. Existing fraud/maintenance tests passed.

Ruff lint and format checks passed for 77 Python files. `pip check` found no dependency
conflicts. No new package dependency was required. Existing dependency deprecations
and MLflow integer-label warnings remain.

The local PostgreSQL schema is `0004`. Native inference, Prometheus and Grafana were
restarted and reported ready. The existing fraud champion was preserved.

No Ollama executable was found on PATH, and the live local endpoint attempt returned
an audited **UNAVAILABLE / ConnectError**. Accepted and rejected structured responses
were tested with controlled HTTP fixtures. A real local model-generated explanation
was not validated; no model was downloaded. Deterministic investigations are fully
functional without it. Docker container runtime remains unverified due to the
previously documented host Docker engine issue.

Reproduce validation from the repository root:

```powershell
$env:AEGIS_TEST_POSTGRES_URL='postgresql+psycopg://aegis:aegis_local@127.0.0.1:55432/aegis'
$env:DO_NOT_TRACK='1'
$env:EVIDENTLY_DISABLE_TELEMETRY='1'
.\.venv\Scripts\python.exe -m pytest --cov=aegis --cov=apps --cov-report=term-missing -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/verify_phase4.py
```

## Boundaries and next handoff

See [investigation operations](investigations.md) for exact training, forecasting,
injection, investigation/export and optional local-AI commands, metric semantics and
fault assumptions. [Deployment operations](deployment.md) covers migration/restart.

Root causes remain hypotheses supported by available evidence. The collector does
not fetch historical infrastructure telemetry; missing signals stay unavailable.
Local AI is constrained to ordering verified evidence and approved steps. Energy
faults are synthetic counterfactual batches. The workload is batch forecasting, not
a new online regression endpoint. Current actors and credentials are development-only.

Phase 5 should consume immutable investigation/report links to create retraining
requests, then enforce fresh data validation, candidate metric/latency gates,
approval state and deployment eligibility through Airflow. Preserve source-quality
vetoes; an explanation or old eligibility flag is not authorization to act.
