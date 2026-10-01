from pathlib import Path

import pandas as pd
import typer

from aegis.cli.reliability import dependencies, emit
from aegis.core.errors import AegisError
from aegis.data.energy import inject
from aegis.data.fraud import digest
from aegis.db.models import AuditEvent
from aegis.reliability.analysis import analyze
from aegis.reliability.policy import load_policy
from aegis.reliability.workload import context, load_predictor, score

app = typer.Typer(no_args_is_help=True, help="One-hour-ahead energy forecast batches")


@app.command("forecast")
def forecast(
    version: int,
    current: Path,
    output: Path,
    policy: Path = Path("configs/reliability/energy.yaml"),
):
    settings, factory, _ = dependencies()
    config, reference, info = context(settings, factory, "energy-demand", version)
    frame = pd.read_csv(current)
    contract = load_policy(policy)
    if set(contract.ranges) != set(config.features.numeric) or set(contract.categories) != set(
        config.features.categorical
    ):
        raise AegisError("Forecast policy must cover all energy features")
    if analyze(reference, frame, config, contract)["recommendation"] == "INVESTIGATE_UPSTREAM":
        raise AegisError("Forecast input failed data-quality checks; investigate source")
    if frame.empty or output.exists():
        raise AegisError("Input must be nonempty and output must not already exist")
    predicted = score(load_predictor(settings, config, info), frame, config)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as handle:
        predicted.to_csv(handle, index=False, lineterminator="\n")
    with factory.begin() as session:
        session.add(
            AuditEvent(
                actor=settings.actor,
                action="energy.forecast",
                resource_type="model_version",
                resource_id=info["model_version_id"],
                details={
                    "rows": len(frame),
                    "input_sha256": digest(current.read_bytes()),
                    "output_sha256": digest(output.read_bytes()),
                    "output": str(output.resolve()),
                    "horizon_hours": 1,
                },
            )
        )
    emit({"path": str(output.resolve()), "rows": len(frame), "lineage": info})


@app.command("inject")
def inject_command(source: Path, output: Path, scenario: str = "occupancy-shift"):
    result = inject(pd.read_csv(source), scenario)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as handle:
        result.to_csv(handle, index=False, lineterminator="\n")
    emit({"path": str(output.resolve()), "scenario": scenario, "rows": len(result)})
