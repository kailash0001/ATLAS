"""Run real reliability scenarios against an existing governed maintenance model."""

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from aegis.core.config import Settings
from aegis.data.fraud import load_dataset
from aegis.data.maintenance import inject
from aegis.db.models import Model, ModelVersion
from aegis.db.session import make_engine, sessions
from aegis.reliability.policy import load_policy
from aegis.reliability.workload import context, evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidently", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    factory = sessions(make_engine(settings.database_url))
    with factory() as session:
        version = session.scalar(
            select(ModelVersion.version)
            .join(Model)
            .where(Model.name == "maintenance-detector", Model.environment == settings.environment)
            .order_by(ModelVersion.version.desc())
        )
    if version is None:
        raise SystemExit("Train first: aegis train --config configs/models/maintenance.yaml")
    config, _, info = context(settings, factory, "maintenance-detector", version)
    _, frames = load_dataset(settings.data_root / config.dataset.name / info["dataset_fingerprint"])
    policy = load_policy(Path("configs/reliability/maintenance.yaml"))
    output = settings.data_root / "reliability" / "phase3-demo"
    output.mkdir(parents=True, exist_ok=True)
    summary = {}
    for scenario in [
        "healthy",
        "drift",
        "performance",
        "sensor-corruption",
        "schema",
        "new-category",
    ]:
        frame = inject(frames["test"], scenario)
        frame.to_csv(output / f"{scenario}.csv", index=False)
        report = evaluate(
            settings,
            factory,
            config.name,
            version,
            frame,
            policy,
            evidently_html=output / "evidently-drift.html"
            if args.evidently and scenario == "drift"
            else None,
        )
        evidence = report["evidence"]
        kinds = {finding["type"] for finding in evidence["findings"]}
        if scenario == "healthy":
            assert report["severity"] == "HEALTHY", evidence
        elif scenario in {"schema", "sensor-corruption", "new-category"}:
            assert report["severity"] == "CRITICAL" and not evidence["retraining_allowed"]
            assert evidence["recommendation"] == "INVESTIGATE_UPSTREAM"
        elif scenario == "drift":
            assert "DATA_DRIFT" in kinds
        elif scenario == "performance":
            assert "PERFORMANCE_DEGRADATION" in kinds
        summary[scenario] = {
            "report_id": report["id"],
            "severity": report["severity"],
            "incident_types": sorted(kinds),
            "recommendation": evidence["recommendation"],
            "retraining_allowed": evidence["retraining_allowed"],
            "current_performance": evidence["performance"]["current"],
        }
    (output / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
