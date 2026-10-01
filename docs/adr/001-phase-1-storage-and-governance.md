# ADR 001: Separate platform governance from experiment tracking

Status: accepted for Phase 1.

## Decision

Use PostgreSQL for Aegis identities, dataset lineage, run summaries, governance state
and audit. Use MLflow OSS for experiment tracking, artifacts and model registry.
Use separate databases even when they share one local PostgreSQL instance.

Treat Aegis as the governance authority, with a durable pending flag and retryable
MLflow alias synchronization. Use candidate/champion aliases rather than legacy
registry stages. Manual promotion requires a recorded reason.

Use synthetic fraud data with a versioned generator and full content hashes. The
default workload has noisy labels and class imbalance. Measured performance is a
demonstration of the workflow, not evidence of real-world fraud accuracy.

## Consequences

The future API and CLI share services. Metadata cannot silently disappear when a
registry write fails. There is no cross-system atomic commit, so sync status is
visible and recovery is explicit. Promotion designates a champion; it is not deployment.

The local native PostgreSQL option uses an isolated workspace cluster when Docker
is unavailable. Compose remains the portable infrastructure path. Both use the same
application services, schema and MLflow server, without substituting fake infrastructure.

References: [MLflow model registry](https://mlflow.org/docs/latest/ml/model-registry/tutorial),
[tracking architecture](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/),
[network protection](https://mlflow.org/docs/latest/self-hosting/security/network/).
