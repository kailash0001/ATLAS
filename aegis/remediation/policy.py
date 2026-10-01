from pathlib import Path

import yaml
from pydantic import Field

from aegis.core.config import StrictModel


class GatePolicy(StrictModel):
    version: str = "1"
    minimum_f1: float = Field(default=0.25, ge=0, le=1)
    minimum_recall: float = Field(default=0.3, ge=0, le=1)
    maximum_mape_percent: float = Field(default=10, gt=0)
    maximum_regression_ratio: float = Field(default=1.05, ge=1)
    maximum_p95_ms: float = Field(default=100, gt=0)
    maximum_latency_ratio: float = Field(default=3, ge=1)
    latency_samples: int = Field(default=50, ge=20, le=500)
    maximum_evidence_age_hours: int = Field(default=24, ge=1, le=168)
    maximum_verification_age_hours: int = Field(default=24, ge=1, le=168)
    maximum_approval_age_hours: int = Field(default=24, ge=1, le=168)


def load_policy(path: Path):
    return GatePolicy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
