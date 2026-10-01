import mlflow.sklearn
import numpy as np
import pytest
from fastapi.testclient import TestClient
from mlflow import MlflowClient
from sqlalchemy import select

from aegis.core.config import Settings
from aegis.data.fraud import load_dataset, setup_dataset
from aegis.db.models import TrainingRun
from aegis.registry.queries import Queries
from aegis.registry.service import GovernanceService
from aegis.serving.config import ServingSettings
from aegis.serving.service import InferenceService
from aegis.training.service import TrainingService
from apps.inference.main import create_app


@pytest.mark.integration
def test_real_mlflow_lifecycle(config, database, tmp_path, monkeypatch):
    # Real tracking/registry/artifact APIs with temporary SQL storage, no mocked metrics.
    monkeypatch.chdir(tmp_path)
    uri = "sqlite:///" + (tmp_path / "mlflow.db").as_posix()
    settings = Settings(mlflow_tracking_uri=uri, environment="test", actor="integration-test")
    service = TrainingService(settings, database)
    path = setup_dataset(config.dataset, tmp_path / "data")
    results = [service.train(config, path, algo) for algo in config.training.algorithms]
    assert len(results) == 2
    assert all(result["registry_sync"] == "synced" for result in results)
    query = Queries(database)
    ranked = query.compare(config.name)
    assert ranked[0]["metrics"]["validation_f1"] >= ranked[1]["metrics"]["validation_f1"]
    assert len(query.runs(config.name)) == 2
    client = MlflowClient(tracking_uri=uri)
    governance = GovernanceService(database, client, "reviewer")
    governance.transition(config.name, ranked[0]["version"], "promote", "Validation reviewed")
    governance.sync(config.name)
    champion = client.get_model_version_by_alias("fraud-detector-test", "champion")
    assert int(champion.version) == ranked[0]["version"]
    mlflow.set_tracking_uri(uri)
    loaded = mlflow.sklearn.load_model(f"models:/fraud-detector-test/{champion.version}")
    _, frames = load_dataset(path)
    probabilities = loaded.predict_proba(frames["test"][config.features.all])
    assert np.isfinite(probabilities).all()
    assert probabilities.shape == (len(frames["test"]), 2)
    artifacts = client.list_artifacts(champion.run_id, "evaluation")
    assert any(a.path == "evaluation/metrics.json" for a in artifacts)
    with database() as session:
        assert all(r.status == "FINISHED" for r in session.scalars(select(TrainingRun)))
    assert len(query.audit()) >= 7
    serving_settings = ServingSettings(mlflow_tracking_uri=uri, environment="test")
    inference = InferenceService(serving_settings, database)
    with TestClient(create_app(serving_settings, inference)) as api:
        assert api.get("/health/ready").status_code == 200
        row = frames["test"].iloc[0]
        response = api.post("/api/v1/predict", json=row[config.features.all].to_dict())
        assert response.status_code == 200, response.text
        result = response.json()
        np.testing.assert_allclose(result["probability"], probabilities[0, 1])
        assert result["version"] == int(champion.version)
        assert (
            api.put(
                f"/api/v1/predictions/{result['prediction_id']}/label",
                json={"actual_label": int(row[config.target])},
            ).status_code
            == 200
        )
        summary = api.get("/api/v1/monitoring/summary").json()
        assert summary["predictions"] == summary["labeled"] == 1
        assert "aegis_serving_ready 1.0" in api.get("/metrics").text


@pytest.mark.integration
def test_failed_tracking_is_recorded(config, database, tmp_path, monkeypatch):
    settings = Settings(mlflow_tracking_uri="sqlite:///" + (tmp_path / "mlflow.db").as_posix())
    service = TrainingService(settings, database)
    path = setup_dataset(config.dataset, tmp_path / "data")

    def unavailable(*args, **kwargs):
        raise ConnectionError("tracking unavailable")

    monkeypatch.setattr(service, "_execute", unavailable)
    with pytest.raises(ConnectionError):
        service.train(config, path, "logistic_regression")
    with database() as session:
        run = session.scalar(select(TrainingRun))
        assert run.status == "FAILED"
        assert run.error == "ConnectionError"
        assert run.completed_at is not None
