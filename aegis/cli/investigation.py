import json
from pathlib import Path

import typer

from aegis.cli.reliability import dependencies, emit
from aegis.investigation.local_ai import save_explanation
from aegis.investigation.service import InvestigationService

app = typer.Typer(no_args_is_help=True, help="Deterministic incident investigations")


def service():
    settings, factory, _ = dependencies()
    return InvestigationService(factory, settings.actor)


@app.command("run")
def run(incident_id: str):
    emit(service().investigate(incident_id))


@app.command("list")
def list_investigations():
    emit(service().list())


@app.command("show")
def show(investigation_id: str):
    emit(service().get(investigation_id))


@app.command("export")
def export(investigation_id: str, output: Path):
    row = service().get(investigation_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Review artifacts are never overwritten implicitly.
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(row, indent=2, default=str, allow_nan=False))
    emit({"path": str(output.resolve()), "investigation_id": investigation_id})


@app.command("explain-local")
def explain_local(investigation_id: str, model: str, port: int = 11434):
    emit(save_explanation(service(), investigation_id, model, port=port))
