# Incident investigation and energy forecasting

Phase 4 turns persisted incident evidence into an auditable investigation. The path
is incident → evidence collection → deterministic rules → likely category → frozen
evidence bundle → human-readable explanation. Optional local AI can arrange that
explanation; it cannot change the category, eligibility, metrics or actions.

## Run the energy workload

Use the project virtual environment from the repository root. Start the existing
PostgreSQL/MLflow services, migrate, and train:

```powershell
.\.venv\Scripts\python.exe scripts/native_infra.py up
.\.venv\Scripts\aegis.exe db upgrade
.\.venv\Scripts\aegis.exe train --config configs/models/energy.yaml
.\.venv\Scripts\aegis.exe models compare energy-demand --metric validation_mape_percent
.\.venv\Scripts\python.exe scripts/verify_phase4.py
```

The demo uses the latest energy version and produces clean, occupancy-shift,
model-degradation and upstream-corruption batches. It persists real reliability
reports and investigations and writes review artifacts under
`data/investigations/phase4-demo/`. It does not promote or deploy a model.
Equivalent task-runner targets are `train-energy` and `investigation-demo`.

Forecast a timestamped batch with an actual version from your registry:

```powershell
.\.venv\Scripts\aegis.exe energy forecast 2 data/investigations/phase4-demo/healthy.csv data/investigations/new-forecasts.csv
.\.venv\Scripts\aegis.exe reliability evaluate energy-demand 2 configs/reliability/energy.yaml --current data/investigations/phase4-demo/occupancy-shift.csv
.\.venv\Scripts\aegis.exe energy inject data/investigations/phase4-demo/healthy.csv data/investigations/new-shift.csv --scenario occupancy-shift
```

The forecast CSV includes `prediction_kw`. Actual `demand_kw` is optional for
forecasting; performance evaluation requires real or explicitly synthetic outcomes.
Forecasting checks data quality and immutable model lineage, then writes an audit
record with input/output hashes. Existing output files are not overwritten. A crash
or failed audit commit can leave a forecast artifact without a success response;
inspect the output and audit before retrying. Energy is a batch workload in this
phase; the existing HTTP service continues to serve binary fraud/maintenance models.

## Time and metric semantics

Energy data consists of hourly UTC demand with a one-hour forecast horizon. Input
features are target hour, weekday, forecast temperature, forecast occupancy and
the observed demand from 24 hours earlier. `issued_at` must precede `timestamp` by
one hour; calendar features must match the target timestamp. Input batches must
be ordered, unique and contiguous hourly readings.

Training, validation and test are chronological 60/20/20 blocks. There is no shuffled
time split. Preprocessing fits training only. The lag's source time precedes forecast
issue time; using earlier test-period observations in later one-step forecasts is
intentional rolling forecasting. No actual future demand or future weather observation
is supplied as a predictor. Forecast weather/occupancy are synthetic inputs declared
available at issue time, not externally measured forecast accuracy.

Baselines are Ridge and RandomForestRegressor. Both are versioned with MLflow
artifacts, dataset hashes, training config and source snapshots. Candidate comparison
supports validation MAE, RMSE and MAPE with **lower values ranked first**. Existing
classification ranking semantics remain unchanged.

MAPE is expressed as a percentage. Targets at or below absolute magnitude `1e-6`
are excluded from the MAPE denominator, with `mape_coverage` explicitly reported.
Performance is insufficient if fewer than 80% of verified outcomes support MAPE;
an all-zero demand batch never becomes falsely HEALTHY. MAE and RMSE remain measured
on all valid outcomes. The default degradation policy is a MAPE increase greater
than **5 percentage points** over the model's validation reference, with at least
100 outcomes and 80% label coverage. Hourly metrics retain counts, MAE, RMSE and MAPE.

The deterministic investigation calculates the share of total absolute forecast
error in hours 14–18 UTC from recorded hourly counts and MAE. It reports that actual
share, without assuming errors must concentrate there.

Fault scenarios are controlled counterfactual batches, not a continuous equipment or
utility simulation. Occupancy shift sets forecast occupancy to 160 for 14–18 UTC and
adjusts demand using a changed response coefficient. Model degradation increases
observed afternoon demand by 80% while holding predictors fixed, isolating performance
change. Upstream corruption sets afternoon occupancy to −999 and temperature to null.
Original versioned data is preserved. Synthetic ground truth is labeled as such.

## Investigate an incident

```powershell
.\.venv\Scripts\aegis.exe reliability incidents
.\.venv\Scripts\aegis.exe investigations run INCIDENT_UUID
.\.venv\Scripts\aegis.exe investigations list
.\.venv\Scripts\aegis.exe investigations show INVESTIGATION_UUID
.\.venv\Scripts\aegis.exe investigations export INVESTIGATION_UUID data/investigations/review.json
```

Investigations also work for existing fraud and maintenance incidents. Each bundle
contains the immutable report fingerprint, model/dataset/run lineage, policy, profiles,
performance, input archive references, and cited facts. Every fact includes a report
ID and JSON pointer so a reviewer can locate its source. Incident history is bounded
to the report observation time; later events do not rewrite the saved snapshot.

Rules version `1` applies this precedence:

| Signals | Likely category | Next investigation |
| --- | --- | --- |
| Invalid schema, ranges, labels or source contract; excessive missing values | UPSTREAM_SYSTEM | Inspect source and validate fresh data; block retraining recommendation |
| Recorded deployment regression | DEPLOYMENT | Compare rollout and version evidence |
| Recorded resource, latency or error-rate degradation | INFRASTRUCTURE | Inspect the affected runtime window |
| Feature distribution changes | DATA | Validate the changed feature population and collection process |
| Measured performance degradation | MODEL | Review recent outcomes and reference performance |
| Prediction drift alone, empty samples or no supporting facts | UNKNOWN | Collect missing evidence |

All matched categories and supporting fact IDs remain in the conclusion. The primary
category is an evidence-supported hypothesis, not proof of causation. A source-quality
failure takes precedence over correlated model degradation even if a report's
eligibility flag says otherwise. Missing CPU, latency or deployment evidence is
explicitly unavailable, never inferred normal. Registry promotion is not deployment.
The current collector reuses recorded report evidence and lineage; it does not fetch
historical infrastructure time series. Runtime/deployment rules can classify recorded
signals, but their causal correlation remains limited by the evidence supplied.

The rule engine may suggest considering a retraining request only for validated
DATA/MODEL evidence with sufficient outcomes and no source/runtime/deployment blocker.
This does not execute retraining or authorize deployment. Every conclusion has
`automatic_action: NONE`.

Repeated investigation of the same incident, report and rules version returns the
same record. A new report produces a new immutable investigation. PostgreSQL row
locks and a unique fingerprint enforce concurrent deduplication; an audit event
records each new investigation. Resolving an incident does not erase its evidence.

## Optional local explanation

Deterministic explanation requires no model server. To use an already installed
local Ollama model, explicitly request it:

```powershell
.\.venv\Scripts\aegis.exe investigations explain-local INVESTIGATION_UUID LOCAL_MODEL_NAME
# An alternate localhost port can be selected with --port.
```

The adapter uses only `127.0.0.1`, disables proxy inheritance and redirects, checks
the local model inventory, and performs no model download. Cloud-named models are
rejected. The request contains selected structured evidence, never arbitrary raw
logs, secrets or executable tools. The response is bounded to 64 KiB and constrained
to a JSON schema of existing fact IDs and allowed next-step IDs. Unsupported fields,
invented IDs, omitted supporting evidence or action IDs cause rejection. Required
quality and missing-evidence steps are restored by the renderer.

Accepted selections only change explanation ordering. All displayed metric values
and prose come from the saved bundle and deterministic templates, preventing invented
numbers from entering the explanation. This is intentionally constrained explanation
assistance, not unrestricted LLM narrative or autonomous root-cause judgment.

Each attempt has its own audited ACCEPTED, UNAVAILABLE or REJECTED result. Network
failure, missing models and malformed output preserve the deterministic investigation
and do not silently replace its conclusion. The adapter follows Ollama's official
[structured-output API](https://github.com/ollama/ollama/blob/main/docs/capabilities/structured-outputs.mdx).

## Phase 5 handoff

Consume immutable investigations and their cited reliability reports when creating
retraining requests. Add Airflow orchestration, dataset-validation gates, candidate
quality comparisons, approval state and deployment eligibility. Re-evaluate evidence
freshness and quality before acting; a stored recommendation is not perpetual
authorization. Preserve the source-corruption veto and separate deterministic policy
decisions from optional local explanation. Safe rollout and the custom control plane
remain Phase 6.
