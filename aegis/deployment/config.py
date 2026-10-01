from pathlib import Path

import yaml
from pydantic import Field

from aegis.core.config import Settings, StrictModel


class ControlSettings(Settings):
    control_token: str = ""
    prometheus_url: str = "http://127.0.0.1:9090"
    airflow_url: str = ""
    airflow_token: str = ""
    deployment_backend: str = "native"
    rollout_policy: Path = Path("configs/deployment/default.yaml")
    kubernetes_context: str = "kind-aegis"
    runtime_image: str = "aegis-platform:local"
    controller_enabled: bool = True


class RolloutPolicy(StrictModel):
    autonomy_level: int = Field(default=1, ge=0, le=4)
    auto_rollback: bool = True
    minimum_requests: int = Field(default=30, ge=10, le=10000)
    minimum_observation_seconds: int = Field(default=60, ge=1, le=3600)
    maximum_window_seconds: int = Field(default=900, ge=60, le=86400)
    maximum_error_rate: float = Field(default=0.02, ge=0, le=1)
    maximum_p95_ms: float = Field(default=250, gt=0, le=60000)
    require_labels: bool = True
    minimum_labels: int = Field(default=20, ge=10)
    minimum_f1: float = Field(default=0.25, ge=0, le=1)
    minimum_recall: float = Field(default=0.3, ge=0, le=1)
    maximum_mape_percent: float = Field(default=10, gt=0)


def load_policy(path):
    return RolloutPolicy.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
