from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from aegis.core.config import load_config
from aegis.data.fraud import load_dataset, setup_dataset
from aegis.db.models import Deployment, ModelVersion, VerificationRun
from aegis.deployment.config import ControlSettings
from aegis.deployment.service import DeploymentService
from aegis.reliability.policy import load_policy
from aegis.remediation.policy import GatePolicy
from aegis.remediation.service import RemediationService
from aegis.remediation.verification import source_hash
from aegis.training.service import TrainingService


@pytest.mark.integration
@pytest.mark.parametrize(
    "workload,algorithm", [("maintenance", "random_forest"), ("energy", "random_forest_regressor")]
)
def test_real_version_routing_and_health_rollback(
    database, tmp_path, monkeypatch, workload, algorithm
):
    config = load_config(Path(f"configs/models/{workload}.yaml"))
    quality = load_policy(Path(f"configs/reliability/{workload}.yaml"))
    config.dataset.samples = 1000
    config.training.algorithms[algorithm]["n_estimators"] = 12
    policy_path = tmp_path / "rollout.yaml"
    policy_path.write_text(
        "minimum_requests: 10\nminimum_labels: 10\nminimum_observation_seconds: 1\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    settings = ControlSettings(
        mlflow_tracking_uri="sqlite:///" + (tmp_path / "mlflow.db").as_posix(),
        data_root=tmp_path / "data",
        environment="test",
        rollout_policy=policy_path,
    )
    path = setup_dataset(config.dataset, settings.data_root)
    baseline = TrainingService(settings, database).train(config, path, algorithm)
    with database.begin() as session:
        verification = VerificationRun(
            source_hash=source_hash(), passed=True, results={"fixture": "trusted test attestation"}
        )
        session.add(verification)
        session.flush()
        verification_id = verification.id
    remediation = RemediationService(settings, database)
    request = remediation.create(
        config.name,
        baseline["version"],
        path,
        algorithm,
        GatePolicy(maximum_latency_ratio=100, maximum_p95_ms=1000),
        quality,
        verification_id,
        "Integration review",
    )
    for stage in ["validate", "train", "evaluate"]:
        request = remediation.stage(request["id"], stage)
    remediation.decide(request["id"], True, "Integration approval")
    service = DeploymentService(settings, database)
    deployment = service.create(request["id"], "Integration canary")
    _, frames = load_dataset(path)
    # Exercise each routing bucket deterministically, while executing actual artifacts.
    choices = iter(range(100))
    events = []
    with patch("aegis.deployment.service.secrets.randbelow", side_effect=lambda _: next(choices)):
        for _, sample in frames["validation"].iloc[:100].iterrows():
            event = service.predict(config.name, sample[config.features.all].to_dict())
            service.label(event["event_id"], float(sample[config.target]))
            events.append(event)
    assert sum(e["candidate"] for e in events) == 10
    assert all(e["latency_ms"] > 0 for e in events)
    assert len({e["version_id"] for e in events}) == 2
    # A failing runtime records real failed attempts and triggers rollback, not promotion.
    with (
        patch("aegis.deployment.service.secrets.randbelow", return_value=0),
        patch.object(
            service.backends, "predict", side_effect=ConnectionError("Controlled runtime outage")
        ),
    ):
        for _ in range(10):
            with pytest.raises(Exception, match="failure recorded"):
                service.predict(
                    config.name, frames["validation"].iloc[0][config.features.all].to_dict()
                )
    result = service.observe(deployment["id"])
    assert result["status"] == "ROLLED_BACK" and result["traffic_percent"] == 0
    event = service.predict(
        config.name, frames["validation"].iloc[0][config.features.all].to_dict()
    )
    assert event["version_id"] == deployment["previous_id"]
    with database() as session:
        assert session.scalar(select(Deployment)).status == "ROLLED_BACK"
        assert session.get(ModelVersion, deployment["candidate_id"]).status == "candidate"
