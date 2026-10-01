"""Evaluate immutable registry artifacts against versioned reference data."""

from datetime import timedelta
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
from sqlalchemy import select

from aegis.core.config import ModelConfig
from aegis.core.errors import AegisError
from aegis.data.fraud import load_dataset
from aegis.db.models import DatasetVersion, Model, ModelVersion, PredictionEvent, TrainingRun, now
from aegis.reliability.analysis import analyze, frame_hash
from aegis.reliability.service import ReliabilityService


def context(settings, factory, name, version_number):
    with factory() as session:
        row = session.execute(
            select(Model, ModelVersion, TrainingRun, DatasetVersion)
            .join(ModelVersion, ModelVersion.model_id == Model.id)
            .join(TrainingRun, TrainingRun.id == ModelVersion.training_run_id)
            .join(DatasetVersion, DatasetVersion.id == TrainingRun.dataset_version_id)
            .where(
                Model.name == name,
                Model.environment == settings.environment,
                ModelVersion.version == version_number,
            )
        ).one_or_none()
        if row is None or row[2].status != "FINISHED":
            raise AegisError("A governed, finished model version is required")
        model, version, run, dataset = row
        config = ModelConfig.model_validate(run.config)
        dataset_path = settings.data_root / config.dataset.name / dataset.fingerprint
        manifest, frames = load_dataset(dataset_path)
        if manifest["fingerprint"] != dataset.fingerprint:
            raise AegisError("Reference fingerprint does not match model lineage")
        info = {
            "model_version_id": version.id,
            "registry_name": model.registry_name,
            "version": version.version,
            "run_id": run.mlflow_run_id,
            "dataset_fingerprint": dataset.fingerprint,
        }
    return config, frames["validation"], info


def score(predictor, frame, config):
    result = frame.copy()
    features = frame[config.features.all].copy()
    features[config.features.numeric] = features[config.features.numeric].astype(float)
    probabilities = np.asarray(predictor.predict(features), dtype=float)
    if config.is_regression:
        if (
            probabilities.shape != (len(frame),)
            or not np.isfinite(probabilities).all()
            or (probabilities < 0).any()
        ):
            raise AegisError("Model returned invalid energy predictions")
        result["prediction_kw"] = probabilities
        return result
    if (
        probabilities.shape != (len(frame), 2)
        or not np.isfinite(probabilities).all()
        or (probabilities < 0).any()
        or (probabilities > 1).any()
        or not np.allclose(probabilities.sum(axis=1), 1)
    ):
        raise AegisError("Model returned invalid binary probabilities")
    result["prediction_probability"] = probabilities[:, 1]
    return result


def evaluate(
    settings,
    factory,
    name,
    version_number,
    current,
    policy,
    *,
    window=None,
    evidently_html: Path | None = None,
):
    config, reference, info = context(settings, factory, name, version_number)
    if set(policy.ranges) != set(config.features.numeric) or set(policy.categories) != set(
        config.features.categorical
    ):
        raise AegisError("Policy must define ranges/categories for every configured feature")
    source = {"kind": "batch"}
    if window is not None:
        if config.is_regression:
            raise AegisError(
                "Energy forecasting uses timestamped batches; "
                "binary serving windows are incompatible"
            )
        if not 1 <= window <= 10080:
            raise AegisError("Window must be between 1 and 10080 minutes")
        end = now()
        with factory() as session:
            events = list(
                session.scalars(
                    select(PredictionEvent)
                    .where(
                        PredictionEvent.model_version_id == info["model_version_id"],
                        PredictionEvent.created_at >= end - timedelta(minutes=window),
                        PredictionEvent.created_at <= end,
                    )
                    .order_by(PredictionEvent.created_at, PredictionEvent.id)
                )
            )
        current = pd.DataFrame(
            [
                {
                    **event.features,
                    config.target: event.actual_label,
                    "prediction_probability": event.probability,
                }
                for event in events
            ],
            columns=[*config.features.all, config.target, "prediction_probability"],
        )
        source = {
            "kind": "serving_events",
            "window_minutes": window,
            "event_ids": [event.id for event in events],
        }
    if current is None:
        raise AegisError("Provide a current dataset or serving window")
    # Archive exact inputs, content addressed, before any scoring; never mutate originals.
    archives = {}
    for label, frame in [("reference", reference), ("current", current)]:
        fingerprint = frame_hash(frame)
        path = settings.data_root / "reliability" / "inputs" / f"{fingerprint}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = frame.to_csv(index=False, lineterminator="\n")
        if path.exists() and path.read_bytes() != content.encode():
            raise AegisError("Archived reliability input checksum mismatch")
        if not path.exists():
            path.write_bytes(content.encode())
        archives[label] = {"path": str(path.resolve()), "sha256": fingerprint}
    preliminary = analyze(reference, current, config, policy)
    # Corrupted readings remain observable but are never passed to a model for remediation.
    if preliminary["recommendation"] != "INVESTIGATE_UPSTREAM" and len(current):
        predictor = load_predictor(settings, config, info)
        reference = score(predictor, reference, config)
        if window is None:
            # Never trust caller-supplied predictions for a batch model evaluation.
            current = score(predictor, current, config)
    evidence = analyze(reference, current, config, policy)
    evidence.update({"lineage": info, "source": source, "inputs": archives})
    if evidently_html is not None:
        from aegis.reliability.evidently_report import export

        evidence["evidently"] = export(reference, current, config, evidently_html)
    return ReliabilityService(factory, settings.actor).save(info["model_version_id"], evidence)


def load_predictor(settings, config, info):
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    remote = mlflow.MlflowClient().get_model_version(info["registry_name"], str(info["version"]))
    if remote.run_id != info["run_id"]:
        raise AegisError("Registry artifact does not match governed run")
    predictor = mlflow.pyfunc.load_model(f"models:/{info['registry_name']}/{info['version']}")
    metadata = predictor.metadata.metadata or {}
    if (
        metadata.get("dataset_fingerprint") != info["dataset_fingerprint"]
        or metadata.get("decision_threshold") != config.training.threshold
    ):
        raise AegisError("Model metadata does not match lineage")
    return predictor
