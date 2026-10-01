from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from aegis.cli.main import app
from aegis.core.config import Settings, load_config
from aegis.data.energy import inject
from aegis.data.fraud import load_dataset, setup_dataset
from aegis.investigation.service import InvestigationService
from aegis.registry.queries import Queries
from aegis.reliability.policy import load_policy
from aegis.reliability.service import ReliabilityService
from aegis.reliability.workload import evaluate
from aegis.training.service import TrainingService


@pytest.mark.integration
def test_real_energy_forecast_and_investigation(database, tmp_path, monkeypatch):
    config = load_config(Path("configs/models/energy.yaml"))
    policy_path = Path("configs/reliability/energy.yaml").resolve()
    policy = load_policy(policy_path)
    config.dataset.samples = 1000
    config.training.algorithms["random_forest_regressor"]["n_estimators"] = 12
    monkeypatch.chdir(tmp_path)
    uri = "sqlite:///" + (tmp_path / "mlflow.db").as_posix()
    settings = Settings(mlflow_tracking_uri=uri, data_root=tmp_path / "data", environment="test")
    path = setup_dataset(config.dataset, settings.data_root)
    result = TrainingService(settings, database).train(config, path, "random_forest_regressor")
    version = result["version"]
    assert (
        Queries(database).compare(config.name, "validation_mape_percent")[0]["version"] == version
    )
    _, frames = load_dataset(path)
    baseline = evaluate(settings, database, config.name, version, frames["test"], policy)
    assert baseline["evidence"]["performance"]["current"]["status"] == "evaluated"
    corrupted = evaluate(
        settings,
        database,
        config.name,
        version,
        inject(frames["test"], "upstream-corruption"),
        policy,
    )
    incidents = ReliabilityService(database, "tester").incidents()
    incident = next(i for i in incidents if i["latest_report_id"] == corrupted["id"])
    investigation = InvestigationService(database, "tester").investigate(incident["id"])
    assert investigation["category"] == "UPSTREAM_SYSTEM"
    assert not investigation["conclusion"]["retraining_eligible"]
    shifted = evaluate(
        settings, database, config.name, version, inject(frames["test"], "occupancy-shift"), policy
    )
    assert any(f["type"] == "PERFORMANCE_DEGRADATION" for f in shifted["evidence"]["findings"])
    incidents = ReliabilityService(database, "tester").incidents()
    incident = next(i for i in incidents if i["latest_report_id"] == shifted["id"])
    report = InvestigationService(database, "tester").investigate(incident["id"])
    assert report["category"] == "DATA"
    assert "MODEL" in report["conclusion"]["contributing_categories"]
    assert any(f["type"] == "ERROR_SEGMENT" for f in report["evidence"]["facts"])
    monkeypatch.setenv("AEGIS_MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv("AEGIS_DATA_ROOT", str(settings.data_root))
    monkeypatch.setenv("AEGIS_ENVIRONMENT", "test")
    current = tmp_path / "unlabeled.csv"
    frames["test"].drop(columns="demand_kw").to_csv(current, index=False)
    output = tmp_path / "forecast.csv"
    response = CliRunner().invoke(
        app,
        [
            "energy",
            "forecast",
            str(version),
            str(current),
            str(output),
            "--policy",
            str(policy_path),
        ],
    )
    assert response.exit_code == 0, response.output
    forecasts = pd.read_csv(output)
    assert len(forecasts) == len(frames["test"])
    assert forecasts.prediction_kw.ge(0).all()
    response = CliRunner().invoke(app, ["investigations", "run", incident["id"]])
    assert response.exit_code == 0, response.output
