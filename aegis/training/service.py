import logging
import os
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path

import mlflow
import mlflow.sklearn
from mlflow import MlflowClient
from mlflow.data.code_dataset_source import CodeDatasetSource
from mlflow.models import infer_signature
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aegis.core.config import ModelConfig, Settings
from aegis.core.errors import ConfigurationError, DataIntegrityError
from aegis.data.fraud import load_dataset
from aegis.db.models import Dataset, DatasetVersion, Model, ModelVersion, TrainingRun, now
from aegis.registry.service import GovernanceService, audit, find_model
from aegis.training.pipeline import build_pipeline, evaluate, validate_features

logger = logging.getLogger("aegis.training")


def code_revision() -> str:
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, timeout=5, text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], timeout=5, text=True
        ).strip()
        return revision + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "uncommitted"


def runtime_metadata() -> dict:
    packages = (
        "aegisml",
        "mlflow",
        "scikit-learn",
        "numpy",
        "pandas",
        "scipy",
        "cloudpickle",
        "skops",
    )
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {name: version(name) for name in packages},
    }


class TrainingService:
    def __init__(self, settings: Settings, sessions: sessionmaker[Session]):
        self.settings, self.sessions = settings, sessions
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "15")
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "2")
        # Keep CLI stdout machine-readable and avoid emoji encoding errors on Windows.
        os.environ["MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT"] = "true"
        os.environ["MLFLOW_PRINT_MODEL_URLS_ON_CREATION"] = "false"
        self.client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)

    def _prepare(self, config: ModelConfig, manifest: dict, algorithm: str, request_id=None) -> str:
        with self.sessions.begin() as session:
            model = session.scalar(select(Model).where(Model.name == config.name))
            if model is None:
                model = Model(
                    name=config.name,
                    owner=config.owner,
                    use_case=config.use_case,
                    risk_level=config.risk_level,
                    environment=self.settings.environment,
                    registry_name=f"{config.name}-{self.settings.environment}",
                )
                session.add(model)
                session.flush()
                audit(session, self.settings.actor, "model.created", model.id, name=model.name)
            elif (model.environment, model.owner, model.use_case, model.risk_level) != (
                self.settings.environment,
                config.owner,
                config.use_case,
                config.risk_level,
            ):
                raise ConfigurationError("Model identity differs from stored governance metadata")
            dataset = session.scalar(select(Dataset).where(Dataset.name == config.dataset.name))
            if dataset is None:
                dataset = Dataset(name=config.dataset.name, source=manifest["source"])
                session.add(dataset)
                session.flush()
            dataset_version = session.scalar(
                select(DatasetVersion).where(DatasetVersion.fingerprint == manifest["fingerprint"])
            )
            if dataset_version is None:
                dataset_version = DatasetVersion(
                    dataset_id=dataset.id, fingerprint=manifest["fingerprint"], manifest=manifest
                )
                session.add(dataset_version)
                session.flush()
            run = TrainingRun(
                model_id=model.id,
                dataset_version_id=dataset_version.id,
                algorithm=algorithm,
                config=config.model_dump(),
                code_revision=code_revision(),
            )
            session.add(run)
            session.flush()
            if request_id is not None:
                from aegis.db.models import RetrainingAttempt

                session.add(RetrainingAttempt(request_id=request_id, training_run_id=run.id))
            audit(
                session,
                self.settings.actor,
                "training.started",
                model.id,
                run_id=run.id,
                algorithm=algorithm,
            )
            return run.id

    def train(
        self, config: ModelConfig, dataset_path: Path, algorithm: str, *, request_id=None
    ) -> dict:
        pipeline = build_pipeline(config, algorithm)
        manifest, frames = load_dataset(dataset_path)
        if manifest["generator"] != config.dataset.model_dump():
            raise DataIntegrityError(
                "Dataset generation settings differ from training configuration"
            )
        for frame in frames.values():
            validate_features(frame, config)
            # A stable floating-point input schema also accepts missing numeric values.
            frame[config.features.numeric] = frame[config.features.numeric].astype(float)
        run_id = self._prepare(config, manifest, algorithm, request_id)
        try:
            result = self._execute(config, manifest, frames, pipeline, algorithm, run_id)
        except Exception as exc:
            with self.sessions.begin() as session:
                run = session.get(TrainingRun, run_id)
                run.status = "FAILED"
                # Avoid persisting connection strings or service responses containing credentials.
                run.error = type(exc).__name__
                run.completed_at = now()
                audit(
                    session,
                    self.settings.actor,
                    "training.failed",
                    run.model_id,
                    run_id=run_id,
                    error_type=type(exc).__name__,
                )
            logger.error("Training failed: run_id=%s error_type=%s", run_id, type(exc).__name__)
            raise
        try:
            GovernanceService(self.sessions, self.client, self.settings.actor).sync(config.name)
            result["registry_sync"] = "synced"
        except Exception as exc:
            result["registry_sync"] = "pending"
            logger.warning("Training succeeded; registry sync pending: %s", type(exc).__name__)
        return result

    def _execute(self, config, manifest, frames, pipeline, algorithm, run_id) -> dict:
        mlflow.set_tracking_uri(self.settings.mlflow_tracking_uri)
        experiment = mlflow.set_experiment(config.experiment)
        with self.sessions() as session:
            revision = session.get(TrainingRun, run_id).code_revision
            registry_name = find_model(session, config.name).registry_name
        with mlflow.start_run(
            experiment_id=experiment.experiment_id, run_name=f"{config.name}-{algorithm}"
        ) as tracked:
            mlflow_run_id = tracked.info.run_id
            with self.sessions.begin() as session:
                run = session.get(TrainingRun, run_id)
                run.mlflow_run_id = mlflow_run_id
                run.mlflow_experiment_id = experiment.experiment_id
            mlflow.set_tags(
                {
                    "aegis.run_id": run_id,
                    "aegis.model": config.name,
                    "aegis.owner": config.owner,
                    "aegis.environment": self.settings.environment,
                    "aegis.dataset_sha256": manifest["fingerprint"],
                    "aegis.code_revision": revision,
                    "aegis.synthetic_data": "true",
                }
            )
            mlflow.log_params(
                {
                    "algorithm": algorithm,
                    "seed": config.training.seed,
                    "threshold": config.training.threshold,
                    **config.training.algorithms[algorithm],
                }
            )
            mlflow.log_dict(config.model_dump(), "config/training.json")
            mlflow.log_dict(manifest, "data/manifest.json")
            runtime = runtime_metadata()
            mlflow.log_dict(runtime, "environment/runtime.json")
            source_root = Path(__file__).resolve().parents[1]
            for source_file in sorted(source_root.rglob("*.py")):
                relative = source_file.relative_to(source_root)
                artifact_dir = (Path("source") / "aegis" / relative.parent).as_posix()
                mlflow.log_artifact(str(source_file), artifact_dir)
            for split, frame in frames.items():
                dataset = mlflow.data.from_pandas(
                    frame,
                    source=CodeDatasetSource(
                        tags={
                            "aegis.generator": f"{config.dataset.name}-v1",
                            "aegis.dataset_sha256": manifest["fingerprint"],
                            "aegis.split": split,
                        }
                    ),
                    targets=config.target,
                    name=f"{config.dataset.name}-{split}",
                )
                mlflow.log_input(dataset, context=split)
            train = frames["train"]
            pipeline.fit(train[config.features.all], train[config.target])
            metrics = {}
            for split in ("validation", "test"):
                metrics.update(
                    {
                        f"{split}_{key}": value
                        for key, value in evaluate(pipeline, frames[split], config).items()
                    }
                )
            mlflow.log_metrics(metrics)
            mlflow.log_dict(metrics, "evaluation/metrics.json")
            example = train[config.features.all].head(5)
            model_info = mlflow.sklearn.log_model(
                pipeline,
                name="model",
                input_example=example,
                signature=infer_signature(
                    example,
                    pipeline.predict(example)
                    if config.is_regression
                    else pipeline.predict_proba(example),
                ),
                pyfunc_predict_fn="predict" if config.is_regression else "predict_proba",
                serialization_format="skops",
                # Only our just-trained local estimators are serialized here.
                # Tree storage is required by RandomForest; never trust arbitrary
                # types discovered in an externally supplied model file.
                skops_trusted_types=["numpy.dtype"]
                + (
                    ["sklearn.tree._tree.Tree"]
                    if algorithm in {"random_forest", "random_forest_regressor"}
                    else []
                ),
                pip_requirements=[
                    f"{package}=={runtime['packages'][package]}"
                    for package in (
                        "scikit-learn",
                        "numpy",
                        "pandas",
                        "scipy",
                        "cloudpickle",
                        "skops",
                    )
                ],
                metadata={
                    "decision_threshold": config.training.threshold,
                    "dataset_fingerprint": manifest["fingerprint"],
                },
            )
            registered = mlflow.register_model(model_info.model_uri, registry_name)
            self.client.set_model_version_tag(
                registry_name, registered.version, "aegis.run_id", run_id
            )
        with self.sessions.begin() as session:
            model = find_model(session, config.name, lock=True)
            run = session.get(TrainingRun, run_id)
            run.status, run.metrics, run.completed_at = "FINISHED", metrics, now()
            model_version = ModelVersion(
                model_id=model.id,
                training_run_id=run_id,
                version=int(registered.version),
                model_uri=f"models:/{registry_name}/{registered.version}",
                features=config.features.model_dump(),
            )
            session.add(model_version)
            model.sync_pending = True
            audit(
                session,
                self.settings.actor,
                "model.registered",
                model.id,
                run_id=run_id,
                version=int(registered.version),
                dataset=manifest["fingerprint"],
            )
        logger.info("Training completed: run_id=%s version=%s", run_id, registered.version)
        return {
            "run_id": run_id,
            "mlflow_run_id": mlflow_run_id,
            "version": int(registered.version),
            "algorithm": algorithm,
            "status": "candidate",
            "metrics": metrics,
        }
