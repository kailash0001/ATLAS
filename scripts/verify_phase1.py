"""Read-only verification of the live trained model and champion artifact."""

import json
from pathlib import Path

import mlflow
import mlflow.sklearn
import numpy as np
from mlflow import MlflowClient

from aegis.core.config import Settings, load_config
from aegis.data.fraud import load_dataset
from aegis.db.session import make_engine, sessions
from aegis.registry.queries import Queries
from aegis.training.pipeline import evaluate


def main():
    settings = Settings()
    config = load_config(Path("configs/models/fraud.yaml"))
    query = Queries(sessions(make_engine(settings.database_url)))
    info = query.inspect_model(config.name)
    assert not info["sync_pending"], "Registry synchronization is pending"
    versions = info["versions"]
    assert {"logistic_regression", "random_forest"} <= {v["algorithm"] for v in versions}
    champions = [v for v in versions if v["status"] == "champion"]
    assert len(champions) == 1, "Promote one candidate with a review reason first"
    champion = champions[0]
    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    remote = client.get_model_version_by_alias(info["registry_name"], "champion")
    assert int(remote.version) == champion["version"]
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    model = mlflow.sklearn.load_model(champion["model_uri"])
    _, frames = load_dataset(
        settings.data_root / config.dataset.name / champion["dataset_fingerprint"]
    )
    measured = evaluate(model, frames["test"], config)
    for key, value in measured.items():
        np.testing.assert_allclose(value, champion["metrics"][f"test_{key}"], atol=1e-12)
    # Verify the pyfunc flavor returns probabilities and accepts nullable numeric input.
    inputs = frames["test"][config.features.all].head(5).copy()
    inputs[config.features.numeric] = inputs[config.features.numeric].astype(float)
    inputs.loc[inputs.index[0], "hour"] = np.nan
    probabilities = mlflow.pyfunc.load_model(champion["model_uri"]).predict(inputs)
    assert probabilities.shape == (5, 2)
    assert np.isfinite(probabilities).all()
    artifacts = client.list_artifacts(champion["mlflow_run_id"], "source/aegis/training")
    assert any(item.path.endswith("pipeline.py") for item in artifacts)
    assert any(event["action"] == "model.champion" for event in query.audit(1000))
    result = {
        "database": "PostgreSQL",
        "tracking_uri": settings.mlflow_tracking_uri,
        "model": config.name,
        "registry_name": info["registry_name"],
        "champion_version": champion["version"],
        "dataset": champion["dataset_fingerprint"],
        "artifact_reload_metrics_match": True,
        "nullable_pyfunc_input": True,
        "source_snapshot_verified": True,
        "registry_sync": "synced",
        "versions": [
            {
                "version": v["version"],
                "algorithm": v["algorithm"],
                "status": v["status"],
                "validation_f1": v["metrics"]["validation_f1"],
                "test_f1": v["metrics"]["test_f1"],
            }
            for v in versions
        ],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
