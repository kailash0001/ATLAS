"""Real HTTP canary exercise on an isolated synthetic demo model, with manual rollback."""

import argparse
import json
from pathlib import Path

import httpx
from sqlalchemy import select

from aegis.core.config import load_config
from aegis.data.fraud import load_dataset, setup_dataset
from aegis.db.models import Model, ModelVersion
from aegis.db.session import make_engine, sessions
from aegis.deployment.config import ControlSettings
from aegis.deployment.service import DeploymentService
from aegis.reliability.policy import load_policy
from aegis.remediation.policy import GatePolicy
from aegis.remediation.service import RemediationService
from aegis.training.service import TrainingService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification-id", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8100")
    args = parser.parse_args()
    settings = ControlSettings(
        rollout_policy=Path("configs/deployment/demo.yaml"), actor="phase6-demo-operator"
    )
    token = settings.control_token or Path(".local/control-token").read_text(encoding="utf-8")
    factory = sessions(make_engine(settings.database_url))
    config = load_config(Path("configs/models/maintenance.yaml"))
    config.name = "maintenance-rollout-demo"
    path = setup_dataset(config.dataset, settings.data_root)
    with factory() as session:
        baseline = session.scalar(
            select(ModelVersion.version)
            .join(Model)
            .where(Model.name == config.name)
            .order_by(ModelVersion.version)
            .limit(1)
        )
    if baseline is None:
        baseline = TrainingService(settings, factory).train(config, path, "random_forest")[
            "version"
        ]
    remediation = RemediationService(settings, factory)
    request = remediation.create(
        config.name,
        baseline,
        path,
        "random_forest",
        GatePolicy(),
        load_policy(Path("configs/reliability/maintenance.yaml")),
        args.verification_id,
        "Isolated Phase 6 synthetic rollout exercise; original workloads are unchanged",
    )
    for stage in ["validate", "train", "evaluate"]:
        request = remediation.stage(request["id"], stage)
    if request["status"] == "AWAITING_APPROVAL":
        remediation.decide(
            request["id"], True, "Reviewed passing gates for isolated synthetic rollout exercise"
        )
    deployer = DeploymentService(settings, factory)
    deployment = deployer.create(request["id"], "Exercise real 10/25/50/100 percent HTTP routing")
    if deployment["status"] != "CANARY":
        raise SystemExit(
            "Demo request already executed; use a fresh test verification for another run"
        )
    _, frames = load_dataset(path)
    data = frames["validation"]
    output = settings.data_root / "deployment" / "phase6-demo"
    output.mkdir(parents=True, exist_ok=True)
    stages = []
    index = 0
    with httpx.Client(
        base_url=args.url, timeout=30, headers={"Authorization": "Bearer " + token}
    ) as client:
        while deployment["status"] == "CANARY":
            count, candidate_count = 0, 0
            while candidate_count < 100:
                sample = data.iloc[index % len(data)]
                index += 1
                response = client.post(
                    f"/api/v1/predict/{config.name}",
                    json={"features": sample[config.features.all].to_dict()},
                )
                response.raise_for_status()
                event = response.json()
                response = client.post(
                    f"/api/v1/labels/{event['event_id']}",
                    json={"actual": int(sample[config.target])},
                )
                response.raise_for_status()
                candidate_count += event["candidate"]
                count += 1
                if count > 5000:
                    raise RuntimeError(
                        "Canary is no longer receiving traffic; inspect deployment health"
                    )
            observed = deployer.observe(deployment["id"])
            stages.append(
                {
                    "traffic_percent": deployment["traffic_percent"],
                    "requests_sent": count,
                    "candidate_requests": candidate_count,
                    "health": observed["health"],
                }
            )
            print(json.dumps(stages[-1]), flush=True)
            deployment = deployer.advance(
                deployment["id"], "Reviewed real HTTP telemetry and ground-truth labels"
            )
        assert deployment["status"] == "PROMOTED"
        rollback = deployer.rollback(
            deployment["id"], "Demonstrate operator rollback and retain the previous version"
        )
        response = client.post(
            f"/api/v1/predict/{config.name}",
            json={"features": data.iloc[0][config.features.all].to_dict()},
        )
        response.raise_for_status()
        assert response.json()["version_id"] == deployment["previous_id"]
    result = {
        "model": config.name,
        "request_id": request["id"],
        "deployment_id": deployment["id"],
        "stages": stages,
        "promoted": True,
        "rollback": rollback,
        "previous_version_verified": True,
    }
    (output / "results.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    print(f"Verified promotion and rollback: {output / 'results.json'}")


if __name__ == "__main__":
    main()
