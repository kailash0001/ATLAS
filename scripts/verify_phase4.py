"""Evaluate real energy scenarios and persist deterministic investigation bundles."""

import json
from pathlib import Path

from sqlalchemy import select

from aegis.core.config import Settings
from aegis.data.energy import inject
from aegis.data.fraud import load_dataset
from aegis.db.models import Model, ModelVersion
from aegis.db.session import make_engine, sessions
from aegis.investigation.service import InvestigationService
from aegis.reliability.policy import load_policy
from aegis.reliability.service import ReliabilityService
from aegis.reliability.workload import context, evaluate, load_predictor, score


def main():
    settings = Settings()
    factory = sessions(make_engine(settings.database_url))
    with factory() as session:
        version = session.scalar(
            select(ModelVersion.version)
            .join(Model)
            .where(Model.name == "energy-demand", Model.environment == settings.environment)
            .order_by(ModelVersion.version.desc())
        )
    if version is None:
        raise SystemExit("Train first: aegis train --config configs/models/energy.yaml")
    config, _, info = context(settings, factory, "energy-demand", version)
    _, frames = load_dataset(settings.data_root / config.dataset.name / info["dataset_fingerprint"])
    policy = load_policy(Path("configs/reliability/energy.yaml"))
    output = settings.data_root / "investigations" / "phase4-demo"
    output.mkdir(parents=True, exist_ok=True)
    reliability = ReliabilityService(factory, settings.actor)
    investigator = InvestigationService(factory, settings.actor)
    summary = {}
    predictor = load_predictor(settings, config, info)
    for scenario in ["healthy", "occupancy-shift", "model-degradation", "upstream-corruption"]:
        current = inject(frames["test"], scenario)
        current.to_csv(output / f"{scenario}.csv", index=False)
        report = evaluate(settings, factory, config.name, version, current, policy)
        evidence = report["evidence"]
        investigation = None
        if scenario == "healthy":
            assert report["severity"] == "HEALTHY", evidence
            score(predictor, current, config).to_csv(output / "forecasts.csv", index=False)
        else:
            incident = next(
                i for i in reliability.incidents() if i["latest_report_id"] == report["id"]
            )
            investigation = investigator.investigate(incident["id"])
            expected = {
                "occupancy-shift": "DATA",
                "model-degradation": "MODEL",
                "upstream-corruption": "UPSTREAM_SYSTEM",
            }[scenario]
            assert investigation["category"] == expected, investigation
            if scenario == "upstream-corruption":
                assert not investigation["conclusion"]["retraining_eligible"]
            (output / f"{scenario}-investigation.json").write_text(
                json.dumps(investigation, indent=2, default=str), encoding="utf-8"
            )
            (output / f"{scenario}-explanation.txt").write_text(
                investigation["explanation"], encoding="utf-8"
            )
        summary[scenario] = {
            "report_id": report["id"],
            "severity": report["severity"],
            "performance": evidence["performance"]["current"],
            "investigation_id": investigation["id"] if investigation else None,
            "category": investigation["category"] if investigation else None,
            "retraining_eligible": investigation["conclusion"]["retraining_eligible"]
            if investigation
            else None,
        }
    (output / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: {k: v for k, v in value.items() if k != "performance"}
                for key, value in summary.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
