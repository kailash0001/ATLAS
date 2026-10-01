from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aegis.core.config import load_config
from aegis.core.errors import DataIntegrityError
from aegis.data.energy import generate, inject, validate_split
from aegis.data.fraud import load_dataset, setup_dataset
from aegis.reliability.analysis import analyze
from aegis.reliability.policy import load_policy
from aegis.training.pipeline import build_pipeline, evaluate
from aegis.training.regression import metrics


@pytest.fixture
def energy():
    config = load_config(Path("configs/models/energy.yaml"))
    config.dataset.samples = 1000
    config.training.algorithms["random_forest_regressor"]["n_estimators"] = 12
    return config, load_policy(Path("configs/reliability/energy.yaml"))


def test_chronological_reproducible_and_causal(energy, tmp_path):
    config, _ = energy
    path = setup_dataset(config.dataset, tmp_path)
    assert setup_dataset(config.dataset, tmp_path) == path
    manifest, frames = load_dataset(path)
    assert manifest["split_method"] == "chronological"
    assert frames["train"].timestamp.max() < frames["validation"].timestamp.min()
    assert frames["validation"].timestamp.max() < frames["test"].timestamp.min()
    all_rows = pd.concat(frames.values(), ignore_index=True)
    np.testing.assert_allclose(all_rows.lag_24h_kw.iloc[24:], all_rows.demand_kw.iloc[:-24])
    times = pd.to_datetime(all_rows.timestamp)
    issued = pd.to_datetime(all_rows.issued_at)
    assert ((times - pd.Timedelta(hours=24)) <= issued).all()
    with pytest.raises(DataIntegrityError):
        validate_split(frames["test"].iloc[::-1], {})
    with pytest.raises(DataIntegrityError):
        validate_split(frames["train"], {"future": frames["test"]})


@pytest.mark.parametrize("algorithm", ["ridge", "random_forest_regressor"])
def test_regression_pipeline_and_quality(energy, tmp_path, algorithm):
    config, policy = energy
    _, frames = load_dataset(setup_dataset(config.dataset, tmp_path))
    model = build_pipeline(config, algorithm)
    model.fit(frames["train"][config.features.all], frames["train"].demand_kw)
    measured = evaluate(model, frames["test"], config)
    assert measured["mae"] >= 0 and measured["mape_percent"] < 15
    reference = frames["validation"].copy()
    reference["prediction_kw"] = model.predict(reference[config.features.all])
    broken = inject(frames["test"], "upstream-corruption")
    report = analyze(reference, broken, config, policy)
    assert report["severity"] == "CRITICAL"
    assert not report["retraining_allowed"]


def test_zero_mape_and_bad_timestamps(energy):
    config, policy = energy
    frame = generate(config.dataset)
    frame["prediction_kw"] = frame.demand_kw
    healthy = analyze(frame, frame, config, policy)
    assert healthy["severity"] == "HEALTHY"
    assert healthy["performance"]["current"]["mape_percent"] == 0
    zero = frame.copy()
    zero["demand_kw"] = 0
    report = analyze(frame, zero, config, policy)
    assert report["performance"]["current"]["status"] == "insufficient"
    assert not report["retraining_allowed"]
    frame.loc[0, "issued_at"] = frame.loc[0, "timestamp"]
    assert analyze(frame, frame, config, policy)["recommendation"] == "INVESTIGATE_UPSTREAM"
    assert "mape_percent" not in metrics(np.zeros(5), np.ones(5))


def test_algorithm_task_mismatch_rejected(energy):
    config, _ = energy
    raw = config.model_dump()
    raw["training"]["algorithms"] = {"logistic_regression": {}}
    with pytest.raises(ValueError):
        type(config).model_validate(raw)
