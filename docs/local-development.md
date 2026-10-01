# Local development

Use Python 3.11/3.12 and work from the repository root. Install the editable package
with its development dependencies. `requirements.lock` records the tested dependency
resolution; use it as a constraint file, not as a replacement for installing the project.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e '.[dev]'
```

Activation is optional: all Windows examples can use `.venv\Scripts\python.exe` and
`.venv\Scripts\aegis.exe` directly. On POSIX activate `.venv/bin/activate`.

## Compose mode

Copy `.env.example` to `.env` once. Run `python scripts/dev.py infra-up`, then
`aegis db upgrade` and `aegis doctor`. Compose starts PostgreSQL 17 and MLflow 3.16.1,
waits for service health and preserves data in named volumes. SQL initialization
creates a separate `mlflow` database on the first cluster startup.

Use `docker compose logs postgres mlflow` for startup problems. Existing unrelated
PostgreSQL/MLflow processes can occupy ports 5432/5000; stop the conflicting process
yourself or consistently change both Compose ports and `.env`.

`python scripts/dev.py infra-down` stops containers without deleting volumes.
Do not use `docker compose down -v` unless intentionally discarding all stored data.
Database migrations use `aegis db upgrade`; normal startup never drops tables.

## Native mode on Windows

`python scripts/native_infra.py up` discovers installed PostgreSQL 17/18 or uses
`AEGIS_PG_BIN`. It initializes only `.local/postgres`, binds to 127.0.0.1:55432,
creates `aegis` and `mlflow` databases, and starts a hidden MLflow process on port
55000. Artifacts and logs live under `.local`. It writes `.env` if absent and preserves
additional settings when the database/MLflow endpoints match. It refuses different
endpoints. Move an existing `.env` to a backup
before intentionally switching modes. Repeated startup reuses the cluster.

```powershell
$env:AEGIS_PG_BIN='C:\Program Files\PostgreSQL\17\bin' # optional
.\.venv\Scripts\python.exe scripts/native_infra.py up
.\.venv\Scripts\aegis.exe db upgrade
.\.venv\Scripts\aegis.exe doctor
```

Stop with `python scripts/native_infra.py down`. The script verifies its saved MLflow
PID before terminating it, and uses PostgreSQL fast shutdown for its own cluster.
Files are preserved. Services do not automatically start after a reboot.

## Configuration

Environment variables override `.env`:

| Variable | Meaning |
| --- | --- |
| `AEGIS_DATABASE_URL` | SQLAlchemy PostgreSQL URI for platform metadata |
| `AEGIS_MLFLOW_TRACKING_URI` | HTTP address of local tracking/registry server |
| `AEGIS_DATA_ROOT` | Root of content-addressed generated datasets |
| `AEGIS_ENVIRONMENT` | `development` or `test`; included in registry name |
| `AEGIS_ACTOR` | Actor recorded for local governance/audit operations |
| `MLFLOW_HTTP_REQUEST_TIMEOUT` | MLflow HTTP timeout, default 15 seconds |
| `MLFLOW_HTTP_REQUEST_MAX_RETRIES` | MLflow retry budget, default 2 |

The fraud configuration lives in `configs/models/fraud.yaml`; use `--config PATH`
for another configuration. Unknown keys, leaked target columns, duplicate features,
invalid splits and unsupported algorithms are rejected. `aegis config-check` checks
estimator hyperparameters as well. Dataset settings must match the manifest when
using `aegis train --dataset PATH`.

Generated datasets are ignored by Git. Their hash includes split file bytes and
generator settings. Dataset setup is reproducible within the pinned environment;
cross-version NumPy/Pandas changes can produce a different fingerprint. Training
logs runtime versions and an Aegis Python source snapshot to MLflow.

## Tests

```powershell
.\.venv\Scripts\python.exe scripts/dev.py test
.\.venv\Scripts\python.exe scripts/dev.py lint
# Also exercise PostgreSQL row locks, constraints and migrations:
$env:AEGIS_TEST_POSTGRES_URL='postgresql+psycopg://aegis:aegis_local@127.0.0.1:55432/aegis'
.\.venv\Scripts\python.exe -m pytest --cov=aegis --cov-report=term-missing
```

Use port 5432 for Compose. The PostgreSQL test fixture uses unique temporary database
names and drops only the database it created. Do not point this development test
account at production infrastructure. Tests do not alter the normal `aegis` database.

## Failure recovery

- `aegis doctor` checks SQL, migration head and MLflow connectivity; nonzero exit means
  at least one prerequisite is unavailable or outdated.
- A failed training operation has a FAILED row and error type in `aegis runs list`.
  Retrying creates a fresh run. Review MLflow artifacts/logs for detailed diagnostics.
- A governance CLI exit code 2 with `registry_sync=pending` means the SQL decision
  committed but registry synchronization needs `aegis models sync NAME`.
- A crash can leave a RUNNING run or orphan MLflow version. Never promote that version
  directly in MLflow; use only governed versions visible in Aegis.
- Do not edit aliases directly in MLflow. Aegis is authoritative and explicit sync
  restores its desired aliases. No background drift reconciler exists in Phase 1.

On this development host Docker Desktop failed during socket initialization. The
native option allows the same real services to run without fixing or reconfiguring
Docker Desktop, WSL or existing database services.
