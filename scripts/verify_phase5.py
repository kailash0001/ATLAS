"""Run all three native retraining workflows; retain real evidence without approval."""

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from aegis.core.config import Settings
from aegis.db.models import Model, ModelVersion
from aegis.db.session import make_engine, sessions
from aegis.reliability.policy import load_policy as load_quality
from aegis.reliability.workload import context
from aegis.remediation.policy import load_policy
from aegis.remediation.service import RemediationService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification-id", required=True)
    args = parser.parse_args()
    settings = Settings()
    factory = sessions(make_engine(settings.database_url))
    service = RemediationService(settings, factory)
    output = settings.data_root / "remediation" / "phase5-demo"
    output.mkdir(parents=True, exist_ok=True)
    summary = {}
    for workload, name, algorithm in [
        ("fraud", "fraud-detector", "random_forest"),
        ("maintenance", "maintenance-detector", "random_forest"),
        ("energy", "energy-demand", "random_forest_regressor"),
    ]:
        with factory() as session:
            versions = list(
                session.scalars(
                    select(ModelVersion)
                    .join(Model)
                    .where(
                        Model.name == name,
                        Model.environment == settings.environment,
                        ModelVersion.status.in_(["candidate", "champion"]),
                    )
                    .order_by(ModelVersion.version.desc())
                )
            )
            if not versions:
                raise SystemExit(f"Train baseline first: {name}")
            baseline = next((v for v in versions if v.status == "champion"), versions[0]).version
        config, _, info = context(settings, factory, name, baseline)
        request = service.create(
            name,
            baseline,
            settings.data_root / config.dataset.name / info["dataset_fingerprint"],
            algorithm,
            load_policy(Path("configs/remediation/default.yaml")),
            load_quality(Path(f"configs/reliability/{workload}.yaml")),
            args.verification_id,
            "Phase 5 shared workflow verification on immutable synthetic baseline data",
        )
        for stage in ["validate", "train", "evaluate"]:
            result = service.stage(request["id"], stage)
        (output / f"{workload}.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
        summary[workload] = {
            "request_id": result["id"],
            "status": result["status"],
            "baseline_version": baseline,
            "candidate_version": result["results"]["training"]["version"],
            "passed": result["results"]["passed"],
            "failed_gates": [g["name"] for g in result["results"]["gates"] if not g["passed"]],
            "measurements": result["results"]["measurements"],
            "approved": False,
            "deployed": False,
        }
        (output / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({workload: summary[workload]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
