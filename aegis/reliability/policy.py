from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import Field, model_validator

from aegis.core.config import StrictModel
from aegis.core.errors import ConfigurationError


class Severity(StrEnum):
    HEALTHY = "HEALTHY"
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentType(StrEnum):
    DATA_DRIFT = "DATA_DRIFT"
    PREDICTION_DRIFT = "PREDICTION_DRIFT"
    PERFORMANCE_DEGRADATION = "PERFORMANCE_DEGRADATION"
    SCHEMA_CHANGE = "SCHEMA_CHANGE"
    MISSING_DATA = "MISSING_DATA"
    OUT_OF_RANGE_FEATURE = "OUT_OF_RANGE_FEATURE"
    LATENCY_DEGRADATION = "LATENCY_DEGRADATION"
    ERROR_RATE_SPIKE = "ERROR_RATE_SPIKE"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    UPSTREAM_DATA_FAILURE = "UPSTREAM_DATA_FAILURE"
    DEPLOYMENT_REGRESSION = "DEPLOYMENT_REGRESSION"


def highest(values):
    return max(values, key=lambda value: list(Severity).index(Severity(value)))


class Policy(StrictModel):
    version: str = "1"
    minimum_rows: int = Field(default=100, ge=20)
    minimum_labels: int = Field(default=100, ge=20)
    minimum_label_coverage: float = Field(default=0.8, gt=0, le=1)
    null_fraction: float = Field(default=0.01, ge=0, lt=1)
    invalid_fraction: float = Field(default=0.01, ge=0, lt=1)
    outlier_fraction: float = Field(default=0.05, ge=0, lt=1)
    drift_distance: float = Field(default=0.15, gt=0, lt=1)
    critical_drift_distance: float = Field(default=0.4, gt=0, le=1)
    f1_drop: float = Field(default=0.1, gt=0, le=1)
    mape_increase_points: float = Field(default=5.0, gt=0)
    ranges: dict[str, tuple[float, float]] = Field(default_factory=dict)
    categories: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.critical_drift_distance <= self.drift_distance:
            raise ValueError("Critical drift threshold must exceed warning threshold")
        if any(low >= high for low, high in self.ranges.values()):
            raise ValueError("Range lower bound must be below upper bound")
        return self


def load_policy(path: Path) -> Policy:
    try:
        return Policy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid reliability policy {path}: {exc}") from exc
