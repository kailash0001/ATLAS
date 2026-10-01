# Phase 1–2 demonstration

1. Start either Compose or native services as documented in the README.
2. Run `aegis db upgrade` and `aegis doctor`. Expect actual database and MLflow checks
   to succeed; a stopped service yields an error, not a simulated healthy state.
3. Run `aegis data setup` twice. The printed dataset path/fingerprint should be identical.
   Inspect `manifest.json` for generator configuration, row counts and checksums.
4. Run `aegis train`. Two actual estimators train on the same training split. Each
   produces its own tracked experiment run and registered candidate version.
5. Run `aegis models compare fraud-detector`. Review validation F1, recall, precision,
   false-positive rate and average precision; do not select using test performance.
6. Open the local MLflow UI. Inspect parameters, metrics, three input dataset contexts,
   evaluation artifacts, source snapshot, model signature and registered versions.
7. Pick a candidate version from the comparison and run
   `aegis models promote fraud-detector VERSION --reason "Reviewed validation and lineage"`.
8. Run `aegis models inspect fraud-detector`. Verify champion status, dataset fingerprint,
   feature list, run/experiment IDs and `sync_pending=false`. Deployment history is
   explicitly unavailable.
9. Run `aegis audit`. Observe training, registration, champion and registry-sync events
   with actor and reason. In MLflow verify the corresponding `champion` alias.
10. Train again if demonstrating replacement. Promote an eligible new candidate;
    the former champion becomes archived and remains inspectable. A rejected version
    cannot be promoted.

Metrics are computed, so exact scores can differ across data/configuration/package
changes. A demonstration should show measured values, including imperfect scores.
This noisy synthetic workload is intended to exercise lineage and operations.

## Phase 2 extension

After migration and champion promotion, start the serving/monitoring stack using
the README instructions. Open `/docs`, `/health/live` and `/health/ready` on port 8000.
Inspect `/api/v1/model` for the actual loaded version.

Run `python scripts/traffic.py --count 300 --rate 15 --concurrency 8 --labels --invalid-every 20`.
Observe real request/error/latency measurements in Grafana. Labels are submitted after
the prediction batch. Inspect label coverage and confusion-based performance; do not
equate HTTP success with model quality. Run `python scripts/verify_phase2.py` after a
scrape to check API evidence, Prometheus and the Grafana datasource.

An incident → retrain → canary → promote/rollback workflow belongs to the later phases
and is not simulated by this demo.
# Phase 3 demonstration

Run `python scripts/dev.py train-maintenance`, then
`python scripts/verify_phase3.py --evidently` with the project virtual environment
and local PostgreSQL/MLflow running. The optional export requires installing
`.[dev,reliability]` with the lockfile constraints. The six scenarios write actual
evidence and incidents; [reliability operations](reliability.md) has exact commands
and [the Phase 3 report](phase-3-report.md) records verified results.


## Phase 6: ATLAS workspace and safe release

Start the native console with `python scripts/native_console.py up`, open
http://127.0.0.1:3100 and use `atlas / atlas_local`. Scroll through the four-stage
3D lifecycle, then enter the workspace. Inspect the three original workloads and
existing incident evidence; the UI reads persisted state and real telemetry.

After final source validation, run an isolated measured rollout:

```powershell
$env:AEGIS_TEST_POSTGRES_URL='postgresql+psycopg://aegis:aegis_local@127.0.0.1:55432/aegis'
.\.venv\Scripts\atlas.exe remediation verify-tests
.\.venv\Scripts\python.exe scripts/verify_phase6.py --verification-id <passed-verification-id>
```

The script explicitly approves only its `maintenance-rollout-demo` candidate after
passing gates. It sends real labeled HTTP traffic at 10, 25, 50 and 100 percent,
promotes, rolls back, and confirms the previous artifact serves again. Evidence is
written to `data/deployment/phase6-demo/results.json`. Existing fraud, maintenance
and energy approval decisions remain unchanged. Open Deployments and Audit to review.

Automatic rollback on measured runtime failure is separately exercised by integration
tests for classification and regression; these tests inject a controlled backend
connection failure after healthy real artifact predictions.
