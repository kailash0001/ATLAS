# Phase 3 implementation and verification

Implemented the reliability subsystem and industrial predictive-maintenance workload.
The platform now detects data contract failures, distribution changes and observed
performance degradation, preserves evidence and manages first-class incidents.

## Deliverables

- `aegis/reliability/analysis.py`: profiles, null/schema/range/category/outlier
  checks, feature and prediction drift, label sufficiency and F1 degradation.
- `policy.py` and `configs/reliability/`: validated, versioned workload policies,
  normalized severities and shared incident vocabulary.
- `workload.py`: governed immutable model loading, validation-reference lineage,
  batch scoring, version-specific serving windows and hashed input archives.
- `service.py`: durable idempotent reports, incident deduplication, occurrence
  history, acknowledgement/resolution and transactional audit.
- `evidently_report.py`: local optional Evidently OSS HTML export with telemetry
  disabled. Aegis policies remain independent and authoritative.
- `aegis/data/maintenance.py` and `configs/models/maintenance.yaml`: reproducible
  sensor data, noisy failure labels, two baseline pipelines and six scenarios.
- Shared training/config/data code now supports both workloads while preserving
  the existing fraud generator and fingerprint format. Maintenance training metrics
  use failure rates. The inference service validates either workload and exposes
  maintenance failure-rate metrics while preserving fraud metric names.
- Migration `0003`: `reliability_reports` and `incidents`, foreign keys, unique
  report fingerprints, severity/status checks and a unique active-incident index.
- CLI `aegis reliability evaluate/reports/incidents/transition/inject`;
  `scripts/verify_phase3.py`, task-runner targets, unit/integration/concurrency tests,
  updated dependency constraints and operating documentation.

Reports reference immutable model versions, policy snapshots and exact input hashes.
PostgreSQL serializes incident observation and transition operations per version.
Healthy observations do not silently resolve incidents. Sensor corruption produces
an upstream-investigation recommendation and disables retraining eligibility.

## Actual local results

Both maintenance estimators were trained and registered in native MLflow with
PostgreSQL metadata. Registry `maintenance-detector-development` has candidate v1
(logistic regression) and candidate v2 (random forest). Neither was promoted in the
development environment. Random forest validation F1 was **0.780524**; held-out
test F1 was **0.786430**, with 2,400 test readings and full synthetic label coverage.
These are workload demonstration results, not real-equipment validation.

The real v2 artifact produced these persisted demo results:

| Scenario | Severity | Observed F1 | Recommendation |
| --- | --- | --- | --- |
| Healthy | HEALTHY | 0.786430 | MONITOR |
| Temperature/vibration drift | HIGH | 0.636116 | REVIEW_MODEL |
| Inverted synthetic outcomes | HIGH | 0.153846 | REVIEW_MODEL |
| Sensor corruption | CRITICAL | Unavailable; scoring skipped | INVESTIGATE_UPSTREAM |
| Missing pressure column | CRITICAL | Unavailable; scoring skipped | INVESTIGATE_UPSTREAM |
| Unknown machine category | CRITICAL | Unavailable; scoring skipped | INVESTIGATE_UPSTREAM |

Every corrupted scenario sets `retraining_allowed=false`. The drift scenario created
data-drift, prediction-drift and performance-degradation evidence. Outcome inversion
created performance degradation without falsely claiming feature drift. Results and
scenario inputs are in `data/reliability/phase3-demo/`; the optional Evidently HTML
report was generated and verified.

Existing fraud champion v3 was preserved. After migration/restart, 200 real HTTP
requests yielded 190 successes and 10 intentional validation rejections, with all
190 successful predictions subsequently labeled and no 5xx responses. The 60-minute
reliability check evaluated 475 stored labeled events including earlier traffic.
The deliberately weak fraud model continued to report F1=0; no metric was invented.
Prometheus was healthy, business metrics matched PostgreSQL, and Grafana's 14 panels
and all 26 PromQL queries verified successfully.

## Verification commands

Final result: **51 passed, 0 skipped, 89% coverage** across `aegis` and `apps`.
Ruff checks and formatting passed for all 63 Python files; `pip check` found no
dependency conflicts. All local documentation links resolve. The additive migration
was applied to the existing development database and the final serving code reloaded.

```powershell
$env:AEGIS_TEST_POSTGRES_URL='postgresql+psycopg://aegis:aegis_local@127.0.0.1:55432/aegis'
$env:DO_NOT_TRACK='1'
$env:EVIDENTLY_DISABLE_TELEMETRY='1'
.\.venv\Scripts\python.exe -m pytest --cov=aegis --cov=apps --cov-report=term-missing -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/verify_phase3.py --evidently
.\.venv\Scripts\python.exe scripts/verify_phase2.py
```

The suite covers reproducible disjoint datasets; healthy versus incomplete evidence;
real drift/corruption; invalid numerics/labels; sparse labels and empty serving
windows; reference/model lineage; real MLflow training and HTTP inference for both
workloads; reports and incident lifecycle; concurrent PostgreSQL report deduplication;
and PostgreSQL migrations through downgrade/upgrade with schema comparison.

Dependency deprecation notices and MLflow integer-label schema warnings remain.
Docker container runtime remains unverified because the pre-existing local Docker
engine startup issue persists; native PostgreSQL/MLflow and monitoring were verified.

## Run and handoff

Use [reliability operations](reliability.md) for exact installation, training,
evaluation, fault injection, incident transition and optional maintenance API commands.
Use [deployment operations](deployment.md) for schema upgrades and process restarts.

Checks are invoked explicitly, not scheduled. Policies require domain calibration;
the data and fault outcomes are synthetic. `retraining_allowed` is an evidence gate,
not an automatic action or production authorization. Incidents expose a conservative
upstream hint; broader root-cause correlation is Phase 4. Authentication, distributed
workers, retraining orchestration and production rollout controls remain in their
designated later phases.

Phase 4 starts from persistent incident/report/audit links and archived input
fingerprints. Add deterministic evidence collection and root-cause rules plus the
energy-forecasting workload. Optional local AI may explain the findings after those
rules run, without controlling production actions or bypassing data-quality checks.
