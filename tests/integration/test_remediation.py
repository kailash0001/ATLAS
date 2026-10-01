from pathlib import Path

import pytest

from aegis.core.config import Settings, load_config
from aegis.data.fraud import setup_dataset
from aegis.db.models import VerificationRun
from aegis.reliability.policy import load_policy
from aegis.remediation.policy import GatePolicy
from aegis.remediation.service import RemediationService
from aegis.remediation.verification import source_hash
from aegis.training.service import TrainingService


@pytest.mark.integration
@pytest.mark.remediation
@pytest.mark.parametrize(
    "workload,algorithm",
    [
        ("fraud", "random_forest"),
        ("maintenance", "random_forest"),
        ("energy", "random_forest_regressor"),
    ],
)
def test_real_shared_retraining_workflow(database, tmp_path, monkeypatch, workload, algorithm):
    config = load_config(Path(f"configs/models/{workload}.yaml"))
    quality = load_policy(Path(f"configs/reliability/{workload}.yaml"))
    config.dataset.samples = 1000
    config.training.algorithms[algorithm]["n_estimators"] = 12
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        mlflow_tracking_uri="sqlite:///" + (tmp_path / "mlflow.db").as_posix(),
        data_root=tmp_path / "data",
        environment="test",
    )
    dataset = setup_dataset(config.dataset, settings.data_root)
    baseline = TrainingService(settings, database).train(config, dataset, algorithm)
    with database.begin() as session:
        verification = VerificationRun(
            source_hash=source_hash(), passed=True, results={"fixture": "trusted test attestation"}
        )
        session.add(verification)
        session.flush()
        verification_id = verification.id
    service = RemediationService(settings, database)
    # Deliberately reject the noisy fraud workload, pass the others when metrics support it.
    policy = GatePolicy(
        minimum_f1=1 if workload == "fraud" else 0.25,
        maximum_latency_ratio=100,
        maximum_p95_ms=1000,
    )
    request = service.create(
        config.name,
        baseline["version"],
        dataset,
        algorithm,
        policy,
        quality,
        verification_id,
        "integration exercise",
    )
    for stage in ["validate", "train", "evaluate"]:
        result = service.stage(request["id"], stage)
    assert result["candidate_version_id"] != result["baseline_version_id"]
    assert result["results"]["validation"]["passed"]
    assert result["results"]["measurements"]["candidate"]["p95_ms"] > 0
    if workload == "fraud":
        assert result["status"] == "REJECTED"
        assert any(not gate["passed"] for gate in result["results"]["gates"])
    else:
        assert result["status"] == "AWAITING_APPROVAL", result["results"]
        approved = service.decide(request["id"], True, "Synthetic integration review")
        assert approved["status"] == "APPROVED"
        assert service.eligible(request["id"])["eligible_for_canary"]
    assert (
        service.stage(request["id"], "train")["candidate_version_id"]
        == result["candidate_version_id"]
    )
