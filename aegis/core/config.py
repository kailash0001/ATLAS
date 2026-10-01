from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aegis.core.errors import ConfigurationError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEGIS_", env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://aegis:aegis_local@localhost:5432/aegis"
    mlflow_tracking_uri: str = "http://localhost:5000"
    data_root: Path = Path("data")
    environment: Literal["development", "test"] = "development"
    actor: str = Field(default="local-developer", min_length=1)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetConfig(StrictModel):
    name: Literal["fraud-synthetic", "maintenance-synthetic", "energy-synthetic"] = (
        "fraud-synthetic"
    )
    seed: int = Field(default=42, ge=0)
    samples: int = Field(default=12000, ge=1000, le=1000000)
    validation_fraction: float = Field(default=0.2, gt=0, lt=0.5)
    test_fraction: float = Field(default=0.2, gt=0, lt=0.5)
    generator_version: Literal["1"] = "1"

    @model_validator(mode="after")
    def split_size(self):
        if self.validation_fraction + self.test_fraction >= 0.8:
            raise ValueError("At least 20% of data must remain for training")
        return self


class Features(StrictModel):
    numeric: list[str]
    categorical: list[str]

    @property
    def all(self) -> list[str]:
        return self.numeric + self.categorical


class TrainingConfig(StrictModel):
    seed: int = Field(default=42, ge=0)
    threshold: float = Field(default=0.5, gt=0, lt=1)
    algorithms: dict[
        Literal["logistic_regression", "random_forest", "ridge", "random_forest_regressor"], dict
    ] = Field(min_length=1)


class ModelConfig(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    owner: str = Field(min_length=1)
    use_case: str = Field(min_length=1)
    risk_level: Literal["low", "medium", "high"]
    experiment: str = Field(min_length=1)
    dataset: DatasetConfig
    features: Features
    target: Literal["is_fraud", "failure", "demand_kw"]
    training: TrainingConfig

    @property
    def is_regression(self) -> bool:
        return self.target == "demand_kw"

    @model_validator(mode="after")
    def unique_features(self):
        expected = {
            "fraud-synthetic": "is_fraud",
            "maintenance-synthetic": "failure",
            "energy-synthetic": "demand_kw",
        }[self.dataset.name]
        regression = {"ridge", "random_forest_regressor"}
        if any((name in regression) != self.is_regression for name in self.training.algorithms):
            raise ValueError("Algorithms must match the workload target type")
        if self.target != expected:
            raise ValueError("Target must match the dataset workload")
        features = self.features.all
        if not features or len(features) != len(set(features)) or self.target in features:
            raise ValueError("Features must be nonempty, unique, and exclude the target")
        return self


def load_config(path: Path) -> ModelConfig:
    try:
        return ModelConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid configuration {path}: {exc}") from exc
