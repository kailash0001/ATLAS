import json
from pathlib import Path

import pandas as pd
import typer

from aegis.core.config import Settings
from aegis.core.errors import AegisError
from aegis.data.maintenance import inject
from aegis.db.session import make_engine, sessions
from aegis.reliability.policy import load_policy
from aegis.reliability.service import ReliabilityService
from aegis.reliability.workload import evaluate

app = typer.Typer(no_args_is_help=True, help="Reliability evidence and incident lifecycle")


def dependencies():
    settings = Settings()
    factory = sessions(make_engine(settings.database_url))
    return settings, factory, ReliabilityService(factory, settings.actor)


def emit(value):
    typer.echo(json.dumps(value, indent=2, default=str, allow_nan=False))


@app.command("evaluate")
def evaluate_command(
    model: str,
    version: int,
    policy: Path,
    current: Path | None = None,
    window_minutes: int | None = None,
    evidently_html: Path | None = None,
):
    """Compare a batch or stored serving window to the model's validation reference."""
    if (current is None) == (window_minutes is None):
        raise AegisError("Supply exactly one of --current or --window-minutes")
    settings, factory, _ = dependencies()
    report = evaluate(
        settings,
        factory,
        model,
        version,
        pd.read_csv(current) if current is not None else None,
        load_policy(policy),
        window=window_minutes,
        evidently_html=evidently_html,
    )
    emit(report)


@app.command("reports")
def reports():
    emit(dependencies()[2].reports())


@app.command("incidents")
def incidents():
    emit(dependencies()[2].incidents())


@app.command("transition")
def transition(incident_id: str, status: str, reason: str):
    emit(dependencies()[2].transition(incident_id, status.upper(), reason))


@app.command("inject")
def inject_command(source: Path, output: Path, scenario: str = "sensor-corruption", seed: int = 42):
    """Create modified maintenance readings without overwriting any existing dataset."""
    if output.exists():
        raise AegisError("Fault output already exists; choose a new path")
    frame = inject(pd.read_csv(source), scenario, seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as handle:
        frame.to_csv(handle, index=False, lineterminator="\n")
    emit({"path": str(output.resolve()), "scenario": scenario, "seed": seed, "rows": len(frame)})
