import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from aegis.core.config import ModelConfig
from aegis.core.errors import ConfigurationError, DataIntegrityError


def build_pipeline(config: ModelConfig, algorithm: str) -> Pipeline:
    if algorithm not in config.training.algorithms:
        raise ConfigurationError(f"Algorithm {algorithm} is not configured")
    estimators = {
        "logistic_regression": LogisticRegression,
        "random_forest": RandomForestClassifier,
        "ridge": Ridge,
        "random_forest_regressor": RandomForestRegressor,
    }
    params = config.training.algorithms[algorithm]
    if "random_state" in params:
        raise ConfigurationError("Use training.seed instead of an algorithm random_state")
    try:
        classifier = estimators[algorithm](random_state=config.training.seed, **params)
        classifier._validate_params()
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"Invalid {algorithm} parameters: {exc}") from exc
    preprocess = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                config.features.numeric,
            ),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("encode", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                config.features.categorical,
            ),
        ]
    )
    return Pipeline([("preprocess", preprocess), ("classifier", classifier)])


def validate_features(frame: pd.DataFrame, config: ModelConfig) -> None:
    missing = set(config.features.all + [config.target]) - set(frame.columns)
    if missing:
        raise DataIntegrityError(f"Missing required columns: {sorted(missing)}")
    numeric = frame[config.features.numeric]
    if any(not pd.api.types.is_numeric_dtype(dtype) for dtype in numeric.dtypes):
        raise DataIntegrityError("Numeric features must contain numeric values")
    if np.isinf(numeric.to_numpy(dtype=float)).any():
        raise DataIntegrityError("Infinite feature values are not allowed")
    if frame[config.features.all].isna().all().any():
        raise DataIntegrityError("Entirely missing features cannot be used for training")


def evaluate(pipeline: Pipeline, frame: pd.DataFrame, config: ModelConfig) -> dict[str, float]:
    truth = frame[config.target]
    if config.is_regression:
        from aegis.training.regression import metrics

        return metrics(truth.to_numpy(), pipeline.predict(frame[config.features.all]))
    probability = pipeline.predict_proba(frame[config.features.all])[:, 1]
    prediction = (probability >= config.training.threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(truth, prediction, labels=[0, 1]).ravel()
    return {
        "precision": float(precision_score(truth, prediction, zero_division=0)),
        "recall": float(recall_score(truth, prediction, zero_division=0)),
        "f1": float(f1_score(truth, prediction, zero_division=0)),
        "roc_auc": float(roc_auc_score(truth, probability)),
        "average_precision": float(average_precision_score(truth, probability)),
        "false_positive_rate": float(fp / max(tn + fp, 1)),
        "fraud_rate" if config.target == "is_fraud" else "failure_rate": float(truth.mean()),
        "predicted_fraud_rate" if config.target == "is_fraud" else "predicted_failure_rate": float(
            prediction.mean()
        ),
        "true_negative": float(tn),
        "false_positive": float(fp),
        "false_negative": float(fn),
        "true_positive": float(tp),
    }
