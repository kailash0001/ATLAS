# Phase 6 rollout operations

The control API routes real predictions to retained, immutable model versions.
Use `/api/v1/predict/{model}` with a `features` object. Returned event IDs accept
delayed labels through authenticated `/api/v1/labels/{id}` requests.

## Governance and stages

A deployment requires a passed source-bound verification, valid dataset and gate
evidence, explicit candidate approval, and an unchanged baseline. SQL transactions
serialize deployments per model. A retry of the same request is idempotent.

Traffic progresses 10 -> 25 -> 50 -> 100 percent, followed by promotion. Every step
requires fresh samples from its own epoch, sufficient observation time and labels,
acceptable errors and p95 latency, and classification F1/recall or regression MAPE.
Missing evidence blocks progression. Defaults are in `configs/deployment/default.yaml`;
`demo.yaml` is explicitly for fast synthetic exercises, not production settings.

Manual rollback is available without fresh approval evidence. Automatic rollback
uses measured unhealthy traffic, restores routing to the previous artifact, and
records the reason. On a promoted deployment it also restores SQL champion state.
MLflow alias synchronization can remain pending if unavailable; this is visible and
retryable. In-flight calls can finish on their selected version after a traffic change.

The original Phase 2 single-champion service remains separate. Phase 6 traffic must
use the control API prediction endpoint to participate in canary evidence.

## CLI and UI

```text
atlas deployments --help
atlas remediation verify-tests
```

The Deployments workspace exposes observe, advance and rollback. The Governance
workspace creates deployments only for approved, eligible requests. Every operator
mutation records a reason and audit event. The default autonomy level is 1: manual
progression with policy-driven rollback protection. Level 2 enables guarded Airflow
scheduling, level 3 starts approved canaries, and level 4 advances healthy stages.
Policy configuration is reviewed YAML, not an unrestricted web editor.

## Native and Kubernetes runtimes

Native mode loads real MLflow artifacts in the local control process. Kubernetes
mode creates a Deployment and Service for each immutable version, waits for readiness,
and routes through those services. Version pods cannot receive the operator token.
RBAC confines the controller to deployment/service operations in namespace `aegis`.

```text
python scripts/kubernetes.py up
python scripts/kubernetes.py deploy
python scripts/kubernetes.py status
```

Prerequisites: working Docker engine, kind and kubectl on PATH. Commands are pinned to
`kind-aegis`; they never deploy to the implicit current context. The local API is
http://127.0.0.1:18100. Images, PostgreSQL, MLflow, migrations, secret generation and
readiness checks are included. The single-node kind artifact directory is a local
hostPath; it is not a multi-node shared-storage design. Train and verify workloads
inside this environment before creating its deployments. Native records are not
silently imported. The web console runs on the host; kind does not install Grafana,
Prometheus or Airflow. Missing integrations stay visible as unavailable.

See the [architecture decision](adr/006-control-plane-and-rollouts.md) and
[validation report](phase-6-report.md) for implementation scope and runtime limits.
