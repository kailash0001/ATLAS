import numpy as np
import pytest
from pydantic import ValidationError

from aegis.core.config import ModelConfig
from aegis.core.errors import ConfigurationError, DataIntegrityError
from aegis.data.fraud import generate
from aegis.training.pipeline import build_pipeline, evaluate, validate_features


@pytest.mark.parametrize("algorithm", ["logistic_regression", "random_forest"])
def test_pipeline_and_metrics(config, algorithm):
    frame = generate(config.dataset)
    pipeline = build_pipeline(config, algorithm)
    pipeline.fit(frame[config.features.all], frame.is_fraud)
    metrics = evaluate(pipeline, frame, config)
    assert 0 <= metrics["f1"] <= 1
    assert 0 <= metrics["false_positive_rate"] <= 1
    inference = frame[config.features.all].head(2).copy()
    inference.loc[0, "merchant_category"] = "unseen-category"
    inference.loc[1, "amount"] = np.nan
    assert pipeline.predict_proba(inference).shape == (2, 2)
    means = pipeline["preprocess"].named_transformers_["numeric"]["scale"].mean_
    np.testing.assert_allclose(means, frame[config.features.numeric].mean())


def test_config_rejects_leakage_and_unknown_keys(config):
    raw = config.model_dump()
    raw["features"]["numeric"].append("is_fraud")
    with pytest.raises(ValidationError):
        ModelConfig.model_validate(raw)
    raw = config.model_dump()
    raw["typo"] = True
    with pytest.raises(ValidationError):
        ModelConfig.model_validate(raw)


def test_invalid_algorithm_and_features(config):
    with pytest.raises(ConfigurationError):
        build_pipeline(config, "unknown")
    config.training.algorithms["random_forest"]["n_estimators"] = -1
    with pytest.raises(ConfigurationError):
        build_pipeline(config, "random_forest")
    with pytest.raises(DataIntegrityError, match="Missing"):
        validate_features(generate(config.dataset).drop(columns="amount"), config)
