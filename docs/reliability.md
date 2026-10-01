# Reliability checks and incident operations

Phase 3 evaluates fraud and industrial predictive-maintenance models using their
immutable MLflow versions. Aegis owns profiles, policies, severity, evidence,
incidents and audit history. Evidently OSS 0.7.23 optionally produces a supplemental
HTML drift report; it does not control platform severity or remediation.

## Run the maintenance workload

From the repository root, with PostgreSQL and MLflow running:

```powershell
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e '.[dev,reliability]'
.\.venv\Scripts\aegis.exe db upgrade
.\.venv\Scripts\aegis.exe train --config configs/models/maintenance.yaml
.\.venv\Scripts\aegis.exe models compare maintenance-detector
.\.venv\Scripts\python.exe scripts/verify_phase3.py --evidently
.\.venv\Scripts\aegis.exe reliability reports
.\.venv\Scripts\aegis.exe reliability incidents
```

The demo uses the latest registered maintenance version, compares its validation
reference with held-out test readings, and persists six real evaluations. It writes
scenario CSVs, `results.json` and `evidently-drift.html` under
`data/reliability/phase3-demo/`. Repeating identical evidence returns the existing
report without incrementing incidents. Training again intentionally creates new runs
and model versions. The demo does not promote a candidate.

For individual evaluations, substitute the actual registry version from training:

```powershell
.\.venv\Scripts\aegis.exe reliability evaluate maintenance-detector 2 configs/reliability/maintenance.yaml --current data/reliability/phase3-demo/healthy.csv
.\.venv\Scripts\aegis.exe reliability evaluate maintenance-detector 2 configs/reliability/maintenance.yaml --current data/reliability/phase3-demo/sensor-corruption.csv
.\.venv\Scripts\aegis.exe reliability evaluate fraud-detector 3 configs/reliability/fraud.yaml --window-minutes 60
```

Exactly one of `--current` or `--window-minutes` is required. Windows are bounded to
seven days and select only events for the requested immutable model version. Labels
are actual stored outcomes; low coverage is reported as insufficient. Batch
probabilities are calculated from the registered model. The reference is always the
checksummed validation split linked to that model's training run. Policy files must
cover every numeric and categorical feature.

## What the checks mean

| Evidence | Method and default policy |
| --- | --- |
| Feature profile | Rows, dtype, null count/fraction, finite numeric count via invalid count, mean, population standard deviation, extrema and p01/p50/p99; category counts |
| Schema | Required columns, numeric dtype/conversion, nonfinite values, permitted categories; additional metadata columns are ignored |
| Missing/range/category | Greater than 1% nulls or invalid values fails the contract; configured inclusive physical ranges and allowed categories |
| Outliers | Current fraction outside reference Q1−3×IQR to Q3+3×IQR; alert above 5% |
| Numeric drift | Empirical two-sample KS distance, WARNING above 0.15 and HIGH above 0.40 |
| Categorical drift | Total variation distance with the same thresholds |
| Prediction drift | KS distance between actual positive-class probabilities; WARNING above 0.15 |
| Performance | F1 and confusion counts at the immutable model threshold; HIGH when F1 decreases by more than 0.10 |
| Sample sufficiency | At least 100 reference/current rows; performance additionally requires 100 valid labels, 80% coverage and both classes |

Distance thresholds measure distribution differences; they are not statistical
significance tests. Thresholds are explicit local demonstration policies and need
domain calibration. F1 on available labels can still have selection bias. Zero F1
is valid evidence, not an unavailable metric. Missing or insufficient evidence never
produces a fully HEALTHY report.

Severity is the highest finding: HEALTHY, INFO, WARNING, HIGH or CRITICAL. INFO means
checks are incomplete without detected violations. Data-contract failures add a
CRITICAL `UPSTREAM_DATA_FAILURE` signal and `INVESTIGATE_UPSTREAM` recommendation.
This is a conservative source-investigation hint, not a proven root cause. Corrupted
batches are profiled but skipped for model scoring. `retraining_allowed=false` blocks
the reliability recommendation; `true` means evidence eligibility only, not an
instruction, authorization or automatic retraining job. Phase 5 will enforce action
gates and orchestration.

Profiles, thresholds, policy hash, input hashes, exact input CSV archives, dataset/run
lineage, findings and recommendations are retained. Scored-frame hashes are separate
from raw-input archive hashes. Reports and incident changes commit together. Input
archives can remain orphaned after a failed evaluation; no automatic cleanup occurs.

## Fault injection

The seeded maintenance generator models temperature, vibration, pressure, RPM,
voltage, current, operating hours and machine type. Labels are noisy synthetic
equipment failures. Data splits are disjoint, reproducible and checksummed.

```powershell
.\.venv\Scripts\aegis.exe reliability inject data/reliability/phase3-demo/healthy.csv data/reliability/my-corruption.csv --scenario sensor-corruption --seed 42
```

Injection refuses to overwrite existing files. `sensor-corruption` changes one third
of temperatures to 999, voltages to null and vibrations to −10. `drift` adds 12 degrees
and 1.5 vibration units; `schema` removes pressure; `new-category` introduces an
unknown device type; `performance` explicitly inverts synthetic observed outcomes
to simulate a concept shift. `healthy` leaves a copy unchanged. None modifies the
versioned training dataset. These are reproducible simulations, not claims about
real equipment or measured production failure behavior.

## Incident lifecycle

Incidents carry model-version, type, feature, severity, status, first/latest report,
occurrence count and timestamps. Open observations deduplicate by model-version,
incident type and feature, retaining the highest observed severity. Evidence-only
report retries are idempotent. New evidence increments occurrences and links its
report through audit history.

```powershell
.\.venv\Scripts\aegis.exe reliability transition INCIDENT_UUID ACKNOWLEDGED "Inspecting the sensor source"
.\.venv\Scripts\aegis.exe reliability transition INCIDENT_UUID RESOLVED "Sensor replaced; subsequent evidence reviewed"
```

Resolution is explicit and audited; a later distinct failing report opens a new
incident. A single healthy batch never silently closes an investigation. PostgreSQL
locks serialize evaluations and transitions per model version; a partial unique
index prevents duplicate active incidents. SQLite remains a test-only concurrency
substitute.

Implemented detectors produce DATA_DRIFT, PREDICTION_DRIFT,
PERFORMANCE_DEGRADATION, SCHEMA_CHANGE, MISSING_DATA, OUT_OF_RANGE_FEATURE and
UPSTREAM_DATA_FAILURE. The shared incident vocabulary also reserves
LATENCY_DEGRADATION, ERROR_RATE_SPIKE, RESOURCE_EXHAUSTION and
DEPLOYMENT_REGRESSION for later correlation and deployment work; Phase 3 does not
invent these findings from unavailable telemetry.

## Optional maintenance HTTP service

After reviewing and explicitly promoting a maintenance candidate, run a separate
single-worker process in a second terminal:

```powershell
.\.venv\Scripts\aegis.exe models promote maintenance-detector 2 --reason "Reviewed synthetic validation evidence for local demo"
$env:AEGIS_SERVING_MODEL='maintenance-detector'
.\.venv\Scripts\python.exe -m uvicorn apps.inference.main:create_app --factory --host 127.0.0.1 --port 8001 --workers 1 --no-access-log
```

Use the existing `/api/v1/predict` and delayed-label endpoints. Example payload:

```json
{"temperature":75.0,"vibration":3.0,"pressure":95.0,"rpm":1500.0,"voltage":230.0,"current":12.0,"operating_hours":10000.0,"machine_type":"pump"}
```

Payloads must match the loaded workload. Maintenance physical limits reject corrupted
inputs with 422. Rejected requests are reflected in HTTP metrics but are not successful
prediction events; evaluate raw upstream batches to retain corruption evidence. Stop
the foreground service with Ctrl+C and remove `AEGIS_SERVING_MODEL` from that terminal
to return to its `.env` setting. Existing fraud serving stays on port 8000.

## Boundaries and next phase

Checks are explicit CLI invocations, not a scheduler. Reports are exposed through the
CLI; the custom console belongs to Phase 6. Evidently runs locally with telemetry
disabled; its independent defaults can disagree with Aegis thresholds, so its output
is labeled supplemental. The adapter follows the official
[Report API](https://evidentlyai.github.io/evidently/api-reference/main/evidently/core/report.html).

Phase 4 should consume `ReliabilityReport.evidence` and incident/audit links, correlate
data/model/infrastructure/deployment signals deterministically, introduce energy
forecasting, and optionally explain evidence using a local model. It must preserve
the data-quality gate and must not delegate operational decisions to an LLM.
