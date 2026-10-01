import json
import os
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from mlflow import MlflowClient
from sqlalchemy import text

from aegis.cli.deployment import app as deployments
from aegis.cli.energy import app as energy
from aegis.cli.investigation import app as investigation
from aegis.cli.reliability import app as reliability
from aegis.cli.remediation import app as remediation
from aegis.core.config import Settings, load_config
from aegis.core.errors import AegisError
from aegis.core.logging import configure_logging
from aegis.data.fraud import setup_dataset
from aegis.db.session import make_engine, sessions
from aegis.registry.queries import Queries
from aegis.registry.service import GovernanceService
from aegis.training.pipeline import build_pipeline
from aegis.training.service import TrainingService

app = typer.Typer(no_args_is_help=True, help="ATLAS control plane CLI.")
app.add_typer(reliability, name="reliability")
app.add_typer(investigation, name="investigations")
app.add_typer(energy, name="energy")
app.add_typer(remediation, name="remediation")
app.add_typer(deployments, name="deployments")
models = typer.Typer(no_args_is_help=True)
runs = typer.Typer(no_args_is_help=True)
data = typer.Typer(no_args_is_help=True)
db = typer.Typer(no_args_is_help=True)
app.add_typer(models, name="models")
app.add_typer(runs, name="runs")
app.add_typer(data, name="data")
app.add_typer(db, name="db")
DEFAULT_CONFIG = Path("configs/models/fraud.yaml")


def emit(value) -> None:
    typer.echo(json.dumps(value, indent=2, default=str))


def dependencies():
    settings = Settings()
    return settings, sessions(make_engine(settings.database_url))


@db.command("upgrade")
def upgrade():
    """Apply versioned platform database migrations."""
    command.upgrade(Config("alembic.ini"), "head")
    emit({"database": "migrated"})


@app.command("doctor")
def doctor():
    """Check SQL connectivity, schema revision, and the MLflow server."""
    settings, factory = dependencies()
    checks = {}
    try:
        with factory() as session:
            checks["database"] = session.execute(text("SELECT 1")).scalar() == 1
            checks["migration"] = session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
            checks["schema_current"] = (
                checks["migration"]
                == ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
            )
    except Exception as exc:
        checks["database_error"] = type(exc).__name__
    try:
        MlflowClient(tracking_uri=settings.mlflow_tracking_uri).search_experiments(max_results=1)
        checks["mlflow"] = True
    except Exception as exc:
        checks["mlflow_error"] = type(exc).__name__
    emit(checks)
    if not (checks.get("database") and checks.get("schema_current") and checks.get("mlflow")):
        raise typer.Exit(1)


@app.command("config-check")
def config_check(config: Path = DEFAULT_CONFIG):
    parsed = load_config(config)
    for algorithm in parsed.training.algorithms:
        build_pipeline(parsed, algorithm)
    emit({"configuration": "valid", "model": parsed.name})


@data.command("setup")
def data_setup(config: Path = DEFAULT_CONFIG):
    parsed = load_config(config)
    path = setup_dataset(parsed.dataset, Settings().data_root)
    emit({"dataset_path": str(path), "fingerprint": path.name})


@app.command("train")
def train(config: Path = DEFAULT_CONFIG, algorithm: str = "all", dataset: Path | None = None):
    """Train configured estimators; each invocation records new experiments/versions."""
    parsed = load_config(config)
    settings, factory = dependencies()
    selected = list(parsed.training.algorithms) if algorithm == "all" else [algorithm]
    # Reject bad configuration before any dataset or database side effects.
    for name in selected:
        build_pipeline(parsed, name)
    path = dataset or setup_dataset(parsed.dataset, settings.data_root)
    service = TrainingService(settings, factory)
    results = []
    for name in selected:
        results.append(service.train(parsed, path, name))
    emit(results)


@models.command("list")
def models_list():
    _, factory = dependencies()
    emit(Queries(factory).models())


@models.command("inspect")
def models_inspect(name: str):
    _, factory = dependencies()
    emit(Queries(factory).inspect_model(name))


@models.command("compare")
def compare(name: str, metric: str = "validation_f1"):
    _, factory = dependencies()
    emit(Queries(factory).compare(name, metric))


def change(name: str, version: int, action: str, reason: str):
    settings, factory = dependencies()
    service = GovernanceService(
        factory, MlflowClient(tracking_uri=settings.mlflow_tracking_uri), settings.actor
    )
    service.transition(name, version, action, reason)
    try:
        service.sync(name)
    except Exception:
        emit(
            {
                "decision": "recorded",
                "registry_sync": "pending",
                "recovery": f"aegis models sync {name}",
            }
        )
        raise typer.Exit(2) from None
    emit({"model": name, "version": version, "action": action, "registry_sync": "synced"})


@models.command("promote")
def promote(name: str, version: int, reason: str = typer.Option(...)):
    """Designate a champion manually. This does not deploy an inference service."""
    change(name, version, "promote", reason)


@models.command("reject")
def reject(name: str, version: int, reason: str = typer.Option(...)):
    change(name, version, "reject", reason)


@models.command("archive")
def archive(name: str, version: int, reason: str = typer.Option(...)):
    change(name, version, "archive", reason)


@models.command("sync")
def sync(name: str):
    settings, factory = dependencies()
    GovernanceService(
        factory, MlflowClient(tracking_uri=settings.mlflow_tracking_uri), settings.actor
    ).sync(name)
    emit({"model": name, "registry_sync": "synced"})


@runs.command("list")
def runs_list(model: str | None = None, limit: int = typer.Option(50, min=1, max=1000)):
    _, factory = dependencies()
    emit(Queries(factory).runs(model, limit))


@app.command("audit")
def audit_list(limit: int = typer.Option(50, min=1, max=1000)):
    _, factory = dependencies()
    emit(Queries(factory).audit(limit))


def main():
    configure_logging()
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "15")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "2")
    try:
        app()
    except AegisError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from None
    except Exception as exc:
        typer.echo(
            f"Operation failed ({type(exc).__name__}). Check configuration and service "
            "health with 'aegis doctor'.",
            err=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
