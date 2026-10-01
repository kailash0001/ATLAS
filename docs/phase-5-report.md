# Phase 5 implementation and verification

Verified locally on 2026-09-23 with Python 3.11.9, PostgreSQL 17 and real MLflow.

## Delivered

One retraining service now supports fraud, maintenance and energy. It persists
requests, trigger evidence, stage claims, training attempts, candidate lineage,
policy-driven evaluation, explicit approvals and canary eligibility. Source-quality
vetoes and evidence freshness are rechecked at each boundary. Managed candidates
cannot bypass gates through manual promotion, even after interrupted training.

The CLI exposes verification, request creation, individual stages, a complete local
run, inspection, approval/rejection and eligibility. Migration `0005` was applied
to the native development database. The Airflow DAG, isolated worker image, Compose
profile and GitHub Actions validation workflow are implemented.

## Checks actually run

- Full suite: **90 passed, zero skipped**, including real MLflow workflows for all
  three workloads and PostgreSQL migration/concurrency tests.
- Coverage: **89%** across `aegis` and `apps`; remediation service 90%, gate evaluator 100%.
- Ruff lint and formatting, `pip check`, and all three workload configurations passed.
- Alembic schema comparison and downgrade/upgrade round trip passed in isolated test databases.
- The source-bound verifier independently ran lint, format, dependency consistency,
  unit and integration tests; every subprocess returned zero.
- Docker Compose configuration validated; Airflow DAG Python compilation passed.
- After migration/restart and retraining, inference readiness, Prometheus readiness
  and Grafana health each returned HTTP 200.

Persisted verification ID: `46a2089b-1fb4-4227-834d-ef6c0ff9ec8a`.
Source hash: `4b3486c9ceba2514d96f6ed2824fc18de4df1e8246260d4730dddb9932ab0bf3`.
Local captured verifier output: `.local/phase5-verification.json`.

Critical tests cover tampered data, failed/stale/source-mismatched verification,
duplicate stage calls, retired baselines, changed champions, stale investigation
evidence, upstream vetoes, expired approval, orphaned candidate protection,
promotion bypass prevention and real passing/rejected workflow paths. Explicit
approval and eligibility were exercised in isolated test databases.

## Native demonstration results

Each request retrained on its existing immutable synthetic dataset and evaluated
candidate and baseline on the same 2,400-row validation split. This demonstrates
workflow execution and gate enforcement; it does not claim improvement from new data.

| Workload | Baseline / candidate | Validation metric | Candidate p95 | Result |
| --- | --- | --- | --- | --- |
| Fraud | 3 / 4 | F1 0.23377; recall 0.16822 | 12.70 ms | REJECTED: F1 and recall below minimum |
| Maintenance | 2 / 3 | F1 0.78052 | 10.97 ms | AWAITING_APPROVAL |
| Energy | 2 / 3 | MAPE 3.13732%; MAE 2.54903 kW | 9.53 ms | AWAITING_APPROVAL |

Request IDs:

- Fraud: `20831f73-c6f8-47e4-86ce-26ac43dc195f`
- Maintenance: `2b98fc18-25b9-4c80-8609-10e28ab2dcde`
- Energy: `8dade09f-c715-4cba-b3c3-0f899f7e1526`

Complete snapshots and measurements are in `data/remediation/phase5-demo/`.
No native candidate was approved, promoted or deployed. Fraud champion version 3
continues serving. Replaying its completed request reused its registered candidate.
The report exporter was corrected to serialize persisted timestamps during this run.

## Runtime limits and handoff

Docker Desktop's Linux engine pipe was unavailable. Consequently the Airflow image
was not built locally and the DAG was not executed through Airflow. The native
service stages were executed end to end; this is not a substitute for Airflow runtime
verification. CI includes real container builds and Airflow DagBag parsing, but the
GitHub workflow has not been executed remotely. Dependency vulnerability scanning
is configured as an advisory CI report and was not run locally.

Development actor identities are not authenticated. Latency is warm model-only
latency. Synthetic thresholds are demonstration policies. Abrupt worker termination
needs operator inspection; there is no automatic crash recovery or lease takeover.
Legacy bootstrap training retains its earlier manual governance path.

Phase 6 should consume fresh approved eligibility for Kubernetes/canary rollout,
then add deployment telemetry, progressive traffic, rollback and the control plane.
See [remediation operations](remediation.md) for exact commands, gate definitions,
Airflow setup, freshness rules and interrupted-run handling.
