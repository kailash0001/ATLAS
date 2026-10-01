import typer

from aegis.cli.reliability import emit
from aegis.db.session import make_engine, sessions
from aegis.deployment.config import ControlSettings
from aegis.deployment.service import DeploymentService

app = typer.Typer(no_args_is_help=True, help="Measured progressive rollout and rollback")


def service():
    settings = ControlSettings()
    return DeploymentService(settings, sessions(make_engine(settings.database_url)))


@app.command("list")
def list_deployments():
    emit(service().list())


@app.command("start")
def start(request_id: str, reason: str = typer.Option(...)):
    emit(service().create(request_id, reason))


@app.command("observe")
def observe(deployment_id: str):
    emit(service().observe(deployment_id))


@app.command("advance")
def advance(deployment_id: str, reason: str = typer.Option(...)):
    emit(service().advance(deployment_id, reason))


@app.command("rollback")
def rollback(deployment_id: str, reason: str = typer.Option(...)):
    emit(service().rollback(deployment_id, reason))
