from pathlib import Path

import typer

from aegis.cli.reliability import dependencies, emit
from aegis.reliability.policy import load_policy as load_quality
from aegis.remediation.policy import load_policy
from aegis.remediation.service import RemediationService
from aegis.remediation.verification import verify

app = typer.Typer(no_args_is_help=True, help="Retraining workflow, quality gates and approvals")


def service():
    settings, factory, _ = dependencies()
    return RemediationService(settings, factory)


@app.command("verify-tests")
def verify_tests():
    settings, factory, _ = dependencies()
    result = verify(factory, settings.actor)
    emit(result)
    if not result["passed"]:
        raise typer.Exit(1)


@app.command("request")
def create(
    model: str,
    baseline: int,
    dataset: Path,
    algorithm: str,
    verification_id: str,
    quality: Path,
    reason: str = typer.Option(...),
    investigation_id: str | None = None,
    policy: Path = Path("configs/remediation/default.yaml"),
):
    emit(
        service().create(
            model,
            baseline,
            dataset,
            algorithm,
            load_policy(policy),
            load_quality(quality),
            verification_id,
            reason,
            investigation_id,
        )
    )


@app.command("stage")
def stage(request_id: str, name: str):
    result = service().stage(request_id, name)
    emit(result)
    if result["status"] in {"FAILED", "REJECTED"}:
        raise typer.Exit(1)


@app.command("run")
def run(request_id: str):
    workflow = service()
    for name in ("validate", "train", "evaluate"):
        result = workflow.stage(request_id, name)
        if result["status"] in {"FAILED", "REJECTED"}:
            emit(result)
            raise typer.Exit(1)
    emit(result)


@app.command("show")
def show(request_id: str):
    emit(service().get(request_id))


@app.command("list")
def list_requests():
    emit(service().list())


@app.command("approve")
def approve(request_id: str, reason: str = typer.Option(...)):
    emit(service().decide(request_id, True, reason))


@app.command("reject")
def reject(request_id: str, reason: str = typer.Option(...)):
    emit(service().decide(request_id, False, reason))


@app.command("eligible")
def eligible(request_id: str):
    emit(service().eligible(request_id))
