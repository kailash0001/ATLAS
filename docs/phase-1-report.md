# Phase 1 implementation and verification

Verified on 2026-09-22 on Windows with Python 3.11.9. The repository was empty at the
start; all project files listed below are new. Existing user code was not replaced.

## 1. Files created

| Area | Files |
| --- | --- |
| Package and setup | `pyproject.toml`, `requirements.lock`, `.env.example`, `.gitignore`, `.dockerignore`, `Makefile`, `README.md` |
| Core | `aegis/__init__.py`, `aegis/core/{config,errors,logging}.py` |
| Data | `aegis/data/fraud.py`, `configs/models/fraud.yaml` |
| Training | `aegis/training/{pipeline,service}.py` |
| Governance | `aegis/registry/{service,queries}.py` |
| Database | `aegis/db/{models,session}.py`, `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_phase_1_governance_schema.py` |
| CLI | `aegis/cli/main.py` |
| Infrastructure | `docker-compose.yml`, `infrastructure/postgres/init.sql`, `infrastructure/containers/mlflow.Dockerfile` |
| Scripts | `scripts/{dev,native_infra,setup_data,verify_phase1}.py` |
| Tests | `tests/conftest.py`, four unit test modules, two integration test modules, package initializers |
| Documentation | `docs/{architecture,local-development,mlops-lifecycle,monitoring,deployment,demo,phase-1-report}.md`, `docs/adr/001-phase-1-storage-and-governance.md` |

Each Python domain package also includes an `__init__.py`. Generated `.env`, `.venv`,
datasets, PostgreSQL cluster, MLflow artifacts and logs are local and ignored by Git.

## 2. Architecture implemented

The CLI calls shared TrainingService, GovernanceService and Queries services.
Configuration uses strict Pydantic models and YAML. SQLAlchemy/Alembic manage platform
metadata in PostgreSQL; a separate PostgreSQL database backs MLflow experiments and
registry. The MLflow server proxies local artifacts to clients.

Data generation is seeded, content-addressed and verified before use. Preprocessing
is fitted only on training rows. Logistic regression and random forest produce real
held-out metrics. MLflow stores signatures, examples, source snapshots, runtime package
versions, configuration, dataset manifests and full serialized pipelines.

Governance is explicit and audited. PostgreSQL row locking and a unique champion
index protect concurrent decisions. MLflow aliases use a retryable pending-sync state.
Promotion is a local registry designation, not model deployment or production approval.

## 3. Database schema

Six platform tables: `models`, `datasets`, `dataset_versions`, `training_runs`,
`model_versions`, `audit_events`, plus Alembic's schema-version table.

Models link to training runs and model versions; training runs link to immutable
dataset versions and MLflow experiment/run IDs. Model versions reference the complete
pipeline artifact. Audit events record actor, action, resource, timestamp and details.
Foreign keys, status constraints, unique lineage keys and indexes are included.
Full fields and ownership boundaries are in [architecture.md](architecture.md).

## 4. Commands and current local state

The native services are running with persistent files under `.local`:

- PostgreSQL: `127.0.0.1:55432`, databases `aegis` and `mlflow`.
- MLflow UI and API: [http://127.0.0.1:55000](http://127.0.0.1:55000).
- Platform schema revision: `0001`.
- Registered model: `fraud-detector-development`.
- Governed version 2: logistic regression, candidate.
- Governed version 3: random forest, development champion; registry synchronization complete.

Run from the repository root:

```powershell
.\.venv\Scripts\aegis.exe doctor
.\.venv\Scripts\aegis.exe models inspect fraud-detector
.\.venv\Scripts\aegis.exe models compare fraud-detector
.\.venv\Scripts\aegis.exe runs list --model fraud-detector
.\.venv\Scripts\aegis.exe audit
.\.venv\Scripts\python.exe scripts/verify_phase1.py
# Restart after reboot, preserving data:
.\.venv\Scripts\python.exe scripts/native_infra.py up
# Stop this workspace's services, preserving data:
.\.venv\Scripts\python.exe scripts/native_infra.py down
```

Fresh installation, Compose mode and dataset/training commands are in the README.

## 5. Tests executed and measured results

Final automated suite: **19 passed, 0 failed, 0 skipped; 85% statement coverage**.
Training service coverage: 95%; governance service: 91%; data generation/integrity: 93%.

```powershell
$env:AEGIS_TEST_POSTGRES_URL='postgresql+psycopg://aegis:aegis_local@127.0.0.1:55432/aegis'
.\.venv\Scripts\python.exe -m pytest --cov=aegis --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
docker compose config --quiet
```

Checks passed for deterministic generation, disjoint splits, corrupted files/manifests,
preprocessing and unseen categories, parameter/schema validation, required governance
reason, rejected-version protection, champion replacement, audit, failed-alias retry,
database uniqueness, concurrent PostgreSQL promotion, migration downgrade/upgrade and
schema drift detection. The MLflow integration uses real local tracking and artifact
APIs to train, register, promote and reload a model. CLI smoke tests cover actual outputs.

Separate live verification against PostgreSQL and the HTTP MLflow server also passed:
two full-size training runs, metadata/lineage persistence, manual development promotion,
alias lookup, downloaded sklearn artifact evaluation matching stored test metrics,
pyfunc predictions with a missing numeric input, source snapshot and audit records.

Measured on 12,000 synthetic transactions, seed 42, with a 60/20/20 split:

| Estimator | Validation F1 | Validation recall | Test F1 |
| --- | ---: | ---: | ---: |
| Logistic regression | 0.175029 | 0.700935 | 0.168088 |
| Random forest | 0.233766 | 0.168224 | 0.136986 |

The random forest was designated champion only to verify the local governance workflow,
using higher validation F1. Its low recall is a material model limitation. Neither
baseline is approved for production fraud use; these numbers are not invented or tuned
to resemble the examples in the project brief. Test performance did not determine selection.

Dataset fingerprint:
`b43daa7d87e2fc4ad97c7e318db16f00e6d23a0f698c9536b985a402cceee2c3`.

The suite emits dependency deprecation warnings and MLflow warnings about integer
dataset label schemas. The saved inference feature signature uses floating-point
numeric inputs, and nullable pyfunc input was explicitly verified.

## 6. Known limitations

- Docker Compose syntax passed validation, but Docker image build/container startup
  could not be tested because this host's Docker Desktop exits during socket initialization.
  The actual PostgreSQL and MLflow lifecycle was verified using native services instead.
- Only the fraud workload is implemented in Phase 1. Synthetic data is not a real fraud benchmark.
- Local actor names and credentials are development-only; no authentication/RBAC.
- No quality-gate automation or deployment. Promotion is manual and records a reason.
- Cross-system writes are eventually consistent. Retry alias sync explicitly; there
  is no periodic reconciler. Abruptly killed jobs and orphan registry versions need review.
- Initial failed development attempts remain visible as FAILED platform runs. One
  earlier MLflow version has no governed platform version because its run failed before
  metadata finalization. It has no champion/candidate alias and is not promotable by Aegis.
- The repository had no commit at training time; revision metadata says `uncommitted`.
  Each successful live run includes a Python source snapshot and package versions.
- The dependency resolution was tested on Windows/Python 3.11. Other supported OS/Python
  combinations and container runtime are not claimed to have been executed here.
- Tests cover core invariants, not production durability, load, authentication or a distributed scheduler.

## 7. Exact Phase 2 entry point

Add `apps/inference` and a model-loader adapter over the existing governed champion URI.
Require FINISHED lineage and `sync_pending=false`, load the complete pipeline, and honor
its feature signature and saved decision threshold. Then implement FastAPI inference,
liveness/readiness, request IDs, model-version metadata, prediction events and real
Prometheus/Grafana telemetry. See [deployment.md](deployment.md) for the ordered handoff.
