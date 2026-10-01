import logging
import math
import os
from dataclasses import dataclass

import mlflow.pyfunc
from mlflow import MlflowClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from aegis.db.models import DatasetVersion, Model, ModelVersion, TrainingRun
from aegis.serving.config import ServingSettings
from aegis.serving.errors import ServingError
from aegis.serving.schemas import FraudFeatures, MaintenanceFeatures

logger = logging.getLogger("aegis.serving")
SCHEMA_REVISION = "0006"


@dataclass(frozen=True)
class LoadedModel:
    name: str
    model_id: str
    version_id: str
    version: int
    registry_name: str
    threshold: float
    numeric: tuple[str, ...]
    feature_names: tuple[str, ...]
    predictor: mlflow.pyfunc.PyFuncModel
    target: str = "is_fraud"


class ModelLoader:
    def __init__(self, settings: ServingSettings, factory: sessionmaker[Session]):
        self.settings, self.factory = settings, factory

    def governed_champion(self) -> dict:
        with self.factory() as session:
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if revision != SCHEMA_REVISION:
                raise ServingError("SCHEMA_NOT_READY", "Apply database migrations before serving")
            model = session.scalar(select(Model).where(Model.name == self.settings.serving_model))
            if model is None or model.environment != self.settings.environment:
                raise ServingError(
                    "MODEL_NOT_CONFIGURED", "No model configured for this environment"
                )
            if model.sync_pending:
                raise ServingError(
                    "REGISTRY_SYNC_PENDING", "Model registry synchronization is pending"
                )
            champions = list(
                session.scalars(
                    select(ModelVersion).where(
                        ModelVersion.model_id == model.id, ModelVersion.status == "champion"
                    )
                )
            )
            if len(champions) != 1:
                raise ServingError("NO_CHAMPION", "Exactly one governed champion is required")
            champion = champions[0]
            run = session.get(TrainingRun, champion.training_run_id)
            if run.status != "FINISHED":
                raise ServingError("RUN_NOT_FINISHED", "Champion training has not completed")
            dataset = session.get(DatasetVersion, run.dataset_version_id)
            return {
                "name": model.name,
                "model_id": model.id,
                "version_id": champion.id,
                "version": champion.version,
                "registry_name": model.registry_name,
                "features": champion.features,
                "threshold": run.config["training"]["threshold"],
                "dataset_fingerprint": dataset.fingerprint,
                "run_id": run.mlflow_run_id,
                "target": run.config["target"],
            }

    def load(self) -> LoadedModel:
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "15")
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "2")
        info = self.governed_champion()
        mlflow.set_tracking_uri(self.settings.mlflow_tracking_uri)
        client = MlflowClient(tracking_uri=self.settings.mlflow_tracking_uri)
        remote = client.get_model_version_by_alias(info["registry_name"], "champion")
        if int(remote.version) != info["version"] or remote.run_id != info["run_id"]:
            raise ServingError(
                "REGISTRY_MISMATCH", "Registry alias does not match governed lineage"
            )
        uri = f"models:/{info['registry_name']}/{info['version']}"
        predictor = mlflow.pyfunc.load_model(uri)
        metadata = predictor.metadata.metadata or {}
        threshold = float(metadata.get("decision_threshold", math.nan))
        if not 0 < threshold < 1 or threshold != info["threshold"]:
            raise ServingError(
                "INVALID_MODEL_METADATA", "Decision threshold does not match lineage"
            )
        if metadata.get("dataset_fingerprint") != info["dataset_fingerprint"]:
            raise ServingError(
                "INVALID_MODEL_METADATA", "Dataset fingerprint does not match lineage"
            )
        features = info["features"]["numeric"] + info["features"]["categorical"]
        signature = predictor.metadata.signature
        if (
            set(features)
            not in (set(FraudFeatures.model_fields), set(MaintenanceFeatures.model_fields))
            or signature is None
            or signature.inputs.input_names() != features
        ):
            raise ServingError(
                "INVALID_MODEL_SIGNATURE", "Model signature is incompatible with inference API"
            )
        # Recheck after slow artifact download: a concurrent promotion invalidates this load.
        if self.governed_champion()["version_id"] != info["version_id"]:
            raise ServingError(
                "CHAMPION_CHANGED", "Champion changed during loading; restart service"
            )
        logger.info(
            "model_loaded",
            extra={
                "context": {"model": info["name"], "version": info["version"], "model_uri": uri}
            },
        )
        return LoadedModel(
            name=info["name"],
            model_id=info["model_id"],
            version_id=info["version_id"],
            version=info["version"],
            registry_name=info["registry_name"],
            threshold=threshold,
            numeric=tuple(info["features"]["numeric"]),
            feature_names=tuple(features),
            predictor=predictor,
            target=info["target"],
        )
