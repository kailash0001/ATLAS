from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mlflow import MlflowClient

from aegis.core.config import Settings, load_config
from aegis.data.fraud import load_dataset, setup_dataset
from aegis.data.maintenance import inject
from aegis.registry.service import GovernanceService
from aegis.reliability.policy import load_policy
from aegis.reliability.workload import evaluate
from aegis.serving.config import ServingSettings
from aegis.serving.service import InferenceService
from aegis.training.service import TrainingService
from apps.inference.main import create_app


@pytest.mark.integration
def test_maintenance_training_serving_reliability(database, tmp_path, monkeypatch):
    config = load_config(Path("configs/models/maintenance.yaml"))
    policy = load_policy(Path("configs/reliability/maintenance.yaml"))
    config.dataset.samples = 1000
    config.training.algorithms["random_forest"]["n_estimators"] = 12
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        mlflow_tracking_uri="sqlite:///" + (tmp_path / "mlflow.db").as_posix(),
        data_root=tmp_path / "data",
        environment="test",
    )
    path = setup_dataset(config.dataset, settings.data_root)
    result = TrainingService(settings, database).train(config, path, "random_forest")
    _, frames = load_dataset(path)
    version = result["version"]
    healthy = evaluate(settings, database, config.name, version, frames["test"], policy)
    assert healthy["evidence"]["performance"]["current"]["status"] == "evaluated"
    assert healthy["severity"] != "CRITICAL"
    broken = evaluate(
        settings,
        database,
        config.name,
        version,
        inject(frames["test"], "sensor-corruption"),
        policy,
    )
    assert broken["severity"] == "CRITICAL"
    assert broken["evidence"]["retraining_allowed"] is False
    assert (
        evaluate(
            settings,
            database,
            config.name,
            version,
            inject(frames["test"], "sensor-corruption"),
            policy,
        )["id"]
        == broken["id"]
    )
    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    governance = GovernanceService(database, client, "tester")
    governance.transition(config.name, version, "promote", "Synthetic integration test")
    governance.sync(config.name)
    serving = ServingSettings(
        mlflow_tracking_uri=settings.mlflow_tracking_uri,
        environment="test",
        serving_model=config.name,
    )
    service = InferenceService(serving, database)
    with TestClient(create_app(serving, service)) as api:
        assert api.get("/health/ready").status_code == 200
        row = frames["test"].iloc[0]
        response = api.post("/api/v1/predict", json=row[config.features.all].to_dict())
        assert response.status_code == 200, response.text
        assert (
            api.put(
                f"/api/v1/predictions/{response.json()['prediction_id']}/label",
                json={"actual_label": int(row.failure)},
            ).status_code
            == 200
        )
        invalid = row[config.features.all].to_dict()
        summary = api.get("/api/v1/monitoring/summary").json()
        assert "predicted_failure_rate" in summary
        assert "predicted_fraud_rate" not in summary
        assert "aegis_model_predicted_failure_rate" in api.get("/metrics").text
        invalid["temperature"] = 999
        assert api.post("/api/v1/predict", json=invalid).status_code == 422
    window = evaluate(settings, database, config.name, version, None, policy, window=60)
    assert window["evidence"]["profiles"]["current"]["rows"] == 1
    assert window["evidence"]["source"]["kind"] == "serving_events"
    assert not window["evidence"]["retraining_allowed"]


def test_evidently_export(tmp_path, monkeypatch):
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv("EVIDENTLY_DISABLE_TELEMETRY", "1")
    pytest.importorskip("evidently")
    from aegis.data.maintenance import generate
    from aegis.reliability.evidently_report import export

    config = load_config(Path("configs/models/maintenance.yaml"))
    config.dataset.samples = 1000
    reference = generate(config.dataset)
    output = tmp_path / "drift.html"
    result = export(reference, inject(reference, "drift"), config, output)
    assert result["version"] == "0.7.23"
    assert output.stat().st_size > 1000
