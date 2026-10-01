# Serving operations and Phase 6 rollout entry point

Phase 2 serves the governed fraud champion through `apps/inference`. Phase 6 adds [measured canary control and rollback](rollouts.md), a native runtime,
and Kubernetes manifests. KServe is an optional future adapter. Promotion alone
does not automatically roll traffic to another model.

## Native Windows

After Phase 1 training and explicit candidate promotion:

```powershell
.\.venv\Scripts\python.exe scripts/native_infra.py up
.\.venv\Scripts\aegis.exe db upgrade
.\.venv\Scripts\python.exe scripts/install_monitoring.py
.\.venv\Scripts\python.exe scripts/native_observability.py up
```

The installer checks official OSS release hashes and writes under `.local/tools`.
Logs, runtime data and saved process identities remain under `.local`. Startup checks
readiness and reuses healthy processes. Stop with:

```powershell
.\.venv\Scripts\python.exe scripts/native_observability.py down
# Stop PostgreSQL/MLflow separately when desired:
.\.venv\Scripts\python.exe scripts/native_infra.py down
```

Shutdown verifies process identity before stopping owned processes. Data is preserved.

## Compose

After Phase 1 setup, migration and promotion in Compose mode:

```text
python scripts/dev.py serving-up
docker compose --profile serving ps
python scripts/dev.py serving-down
```

The optional profile preserves the default empty-project infrastructure bootstrap.
Named volumes retain data. Services listen only on localhost on the host.

## Promotion and restart

Promote with `aegis models promote ... --reason ...`, ensure aliases are synchronized,
then restart inference. In Compose use `docker compose --profile serving restart inference`.
In native mode use observability `down` then `up`, which also restarts monitoring.
The previous loaded model becomes unready rather than silently following a new alias.

## Phase 3 operations

Apply migration `0003` and restart existing inference processes. For native mode,
use observability `down` then `up`; for Compose, rebuild and restart inference after
migrating. This updates the loader's expected schema revision. Follow
[reliability operations](reliability.md) to train maintenance, run fault scenarios,
evaluate serving windows, and inspect reports/incidents. The optional maintenance
API uses a separate process and port; existing fraud governance is preserved.

## Phase 4 operations

Apply migration `0004`, then restart the existing native inference/monitoring processes
with `native_observability.py down` followed by `up`. Compose inference likewise needs
rebuilding/restarting after migration. See [investigations](investigations.md) for
energy training, forecasting, fault scenarios and deterministic/local explanations.
The energy workload runs as explicit batches; binary HTTP serving remains compatible.

## Phase 5 operations and Phase 6 entry point

Apply migration `0005` and restart inference after upgrading. Follow
[remediation operations](remediation.md) to verify tests, create requests, run the
native or Airflow workflow, inspect gates and explicitly review passing candidates.
Managed candidate promotion now enforces request approval and freshness.

Phase 6 should consume `remediation eligible` immediately before rollout and recheck
the same candidate and baseline. The result is a canary eligibility decision, not a
deployment. Safe rollout infrastructure and the custom UI remain Phase 6.
