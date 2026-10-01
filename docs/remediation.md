# Retraining, gates and approval

Phase 5 implements one workflow for fraud, predictive maintenance and energy demand.
Migration `0005` adds `verification_runs`, `retraining_requests` and
`retraining_attempts`. Apply `aegis db upgrade` and restart existing inference
processes after migrating. The expected serving schema is now `0005`.

## Native workflow

Run these commands from the repository root with the project environment activated.
Use `aegis models inspect MODEL` to choose a baseline and locate its immutable dataset.
For a model with a champion, the request must use that champion. An eligible candidate
can serve as an explicit bootstrap baseline when there is no champion.

```text
aegis remediation verify-tests
aegis remediation request MODEL BASELINE DATASET ALGORITHM VERIFICATION_ID QUALITY --reason "Reviewed retraining need"
aegis remediation run REQUEST_ID
aegis remediation show REQUEST_ID
aegis remediation approve REQUEST_ID --reason "Reviewed metrics, latency and lineage"
aegis remediation eligible REQUEST_ID
```

Replace uppercase placeholders with actual values. `QUALITY` is one of
`configs/reliability/fraud.yaml`, `maintenance.yaml` or `energy.yaml`. The default
gate policy is `configs/remediation/default.yaml`; `--policy` accepts a reviewed
alternative. `DATASET` must be its canonical directory under `AEGIS_DATA_ROOT`.
Algorithms are configured on the baseline workload: `random_forest` for the binary
workloads and `random_forest_regressor` for energy.

`verify-tests` actually runs lint, formatting, dependency consistency, unit tests and
integration tests, including the three retraining workflows. It persists the result
and a source hash, rather than accepting a caller-supplied pass flag. Set
`AEGIS_TEST_POSTGRES_URL` to include PostgreSQL concurrency and migration tests;
otherwise those optional tests skip. Install `.[dev,reliability]` to include Evidently.
Verification and requests must be created in the same source/runtime environment.
Editing tracked inputs invalidates eligibility; create fresh verification and a new
request. Dependency downloads and security scanning are separate CI steps.

For investigation-driven requests add `--investigation-id INVESTIGATION_ID`. The
deterministic DATA/MODEL conclusion must permit retraining, refer to the requested
baseline, and remain the unresolved incident's latest report. Upstream corruption,
stale or superseded evidence, and local AI explanations cannot authorize retraining.
Manual requests require a reason and still pass every dataset and candidate gate.
There is no automatic incident polling or unattended approval.

## State and gates

```text
REQUESTED -> VALIDATING -> VALIDATED -> TRAINING -> TRAINED -> EVALUATING
                                                               |
                                          REJECTED or AWAITING_APPROVAL
                                                               |
                                                   APPROVED or REJECTED
```

Execution exceptions produce FAILED. Stage claims are row-locked on PostgreSQL.
Repeated completed stages reuse results. Concurrent attempts cannot start the same
training stage twice. A training attempt is linked before training begins, so a
candidate left behind by interruption remains subject to its request's approval.

Every stage reloads and validates dataset checksums, feature schemas, split integrity
and source quality. Training fits preprocessing and models only on the training split.
Candidate and baseline are scored on the same new validation split; test metrics are
retained for reporting and do not select the candidate. Gates include:

- Loadable artifacts, matching feature signatures and valid prediction output.
- Sufficient evaluation rows and label coverage.
- Classification F1 at least 0.25 and no F1 regression; recall at least 0.30 and no regression.
- Energy MAPE at most 10%, with no more than 5% relative worsening versus baseline.
- Warm single-row prediction p95 at most 100 ms and at most 3 times baseline p95.
- Passing source-matched test verification and complete dataset validation.

Latency is measured over 50 predictions after five warmups. It excludes HTTP,
database and network costs, so it is a local model benchmark rather than an end-to-end
serving SLO. Workloads and thresholds are synthetic demonstration policies.

Default evidence, verification and approval lifetimes are 24 hours. Eligibility
rechecks freshness, current champion, candidate status and registry synchronization.
Use `reject` with a reason to reject an awaiting candidate. Rejected/failed/expired
requests require new verification and a new request; there is no gate override.
Managed candidates cannot bypass approval through `models promote`, including
orphaned candidates. Legacy `aegis train` candidates retain the earlier manual
bootstrap governance path. Actor names remain development configuration, not an
authenticated separation-of-duties system.

A killed worker can leave a running stage. Do not blindly retry training: inspect the
request, attempt and run first, stop the old worker, then create fresh verification
and a replacement request if necessary. Automatic crash reconciliation is not
implemented. The old managed candidate remains blocked.

## Airflow on Linux containers

Airflow is isolated from the ML dependency environment. The image uses Airflow 3.1.8
with its own PostgreSQL metadata database and `/opt/aegis-venv` for Aegis. The local
`standalone` process starts Airflow components with LocalExecutor. A running Linux
Docker engine is required. From the repository root, using Compose infrastructure:

```text
docker compose -f docker-compose.yml -f infrastructure/airflow/compose.yaml --profile orchestration up -d --build
docker compose -f docker-compose.yml -f infrastructure/airflow/compose.yaml --profile orchestration exec -w /opt/aegis airflow /opt/aegis-venv/bin/aegis db upgrade
docker compose -f docker-compose.yml -f infrastructure/airflow/compose.yaml --profile orchestration exec -w /opt/aegis airflow /opt/aegis-venv/bin/aegis train --config configs/models/maintenance.yaml
docker compose -f docker-compose.yml -f infrastructure/airflow/compose.yaml --profile orchestration exec -w /opt/aegis airflow /opt/aegis-venv/bin/aegis remediation verify-tests
```

Create the request using the same `exec -w /opt/aegis airflow /opt/aegis-venv/bin/aegis`
prefix. Dataset paths are `/opt/aegis/data/NAME/FINGERPRINT`. Use that container's
verification ID and registry versions. Native and Compose infrastructure have
different databases and MLflow servers; do not mix their IDs or settings.

Open Airflow at `http://127.0.0.1:8080`, sign in as `aegis` with the generated Simple
Auth Manager password shown in Airflow's local logs/state, unpause `aegis_retraining`
and trigger it with JSON configuration `{"request_id":"ACTUAL_UUID"}`. The DAG runs
`validate_dataset -> train_register -> evaluate_quality_gates`, passing only the
request ID between tasks. It never approves or deploys. A rejected gate produces a
failed Airflow task while retaining the complete REJECTED evidence in Aegis.
Automatic task retries are disabled to make interrupted training explicit.

## CI and Phase 6 handoff

GitHub Actions validates lint/format, dependency consistency, all tests with PostgreSQL,
coverage and three model configurations. A separate job validates Compose, builds
inference, MLflow and Airflow images, and parses the DAG with real Airflow. A dependency
audit uploads a JSON report; it is advisory (`continue-on-error`) pending triage and
does not silently claim the dependency set is vulnerability-free.

`eligible` returns `eligible_for_canary: true` and `deployed: false` only after explicit
approval. Phase 6 must consume and recheck this decision immediately before rollout.
Kubernetes, canaries, deployment telemetry, rollback and the custom control plane
remain Phase 6. No deployment occurs in this phase.

See [Phase 5 verification](phase-5-report.md) for commands and outcomes actually run.
