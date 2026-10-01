import logging
import threading
import time
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from aegis.db.models import AuditEvent, PredictionEvent, now
from aegis.serving.config import ServingSettings
from aegis.serving.errors import ServingError
from aegis.serving.loader import LoadedModel, ModelLoader
from aegis.serving.schemas import FraudFeatures, MaintenanceFeatures, PredictionResponse

logger = logging.getLogger("aegis.serving")


class InferenceService:
    def __init__(self, settings: ServingSettings, factory: sessionmaker[Session], loader=None):
        self.settings, self.factory = settings, factory
        self.loader = loader or ModelLoader(settings, factory)
        self.loaded: LoadedModel | None = None
        self.startup_error = "MODEL_NOT_LOADED"
        self.capacity = threading.BoundedSemaphore(settings.serving_max_concurrency)

    def start(self) -> None:
        try:
            self.loaded = self.loader.load()
            self.startup_error = ""
        except Exception as exc:
            self.startup_error = exc.code if isinstance(exc, ServingError) else "MODEL_LOAD_FAILED"
            logger.error(
                "model_load_failed",
                extra={
                    "context": {"error_code": self.startup_error, "error_type": type(exc).__name__}
                },
            )

    def ready(self) -> LoadedModel:
        if self.loaded is None:
            raise ServingError(self.startup_error, "Model unavailable; inspect logs and restart")
        try:
            current = self.loader.governed_champion()
        except SQLAlchemyError as exc:
            raise ServingError("DATABASE_UNAVAILABLE", "Metadata database is unavailable") from exc
        if current["version_id"] != self.loaded.version_id:
            raise ServingError(
                "CHAMPION_CHANGED", "Loaded model is no longer champion; restart service"
            )
        return self.loaded

    def predict(
        self, features: FraudFeatures | MaintenanceFeatures, request_id: str
    ) -> PredictionResponse:
        if not self.capacity.acquire(blocking=False):
            raise ServingError("OVERLOADED", "Inference capacity is busy; retry later", 429)
        try:
            loaded = self.ready()
            if set(features.model_dump()) != set(loaded.feature_names):
                raise ServingError(
                    "INVALID_WORKLOAD", "Payload does not match the loaded model", 422
                )
            frame = pd.DataFrame([features.model_dump()], columns=loaded.feature_names)
            frame[list(loaded.numeric)] = frame[list(loaded.numeric)].astype(float)
            start = time.perf_counter()
            try:
                probabilities = np.asarray(loaded.predictor.predict(frame), dtype=float)
                if (
                    probabilities.shape != (1, 2)
                    or not np.isfinite(probabilities).all()
                    or (probabilities < 0).any()
                    or (probabilities > 1).any()
                    or not np.isclose(probabilities.sum(), 1)
                ):
                    raise ValueError("Invalid probability output")
            except Exception as exc:
                raise ServingError(
                    "INFERENCE_FAILED", "Model could not produce a valid prediction", 500
                ) from exc
            probability = float(probabilities[0, 1])
            event = PredictionEvent(
                request_id=request_id,
                model_version_id=loaded.version_id,
                features=features.model_dump(),
                probability=probability,
                predicted_class=int(probability >= loaded.threshold),
                threshold=loaded.threshold,
                inference_ms=(time.perf_counter() - start) * 1000,
            )
            try:
                with self.factory.begin() as session:
                    session.add(event)
                    session.flush()
            except SQLAlchemyError as exc:
                raise ServingError(
                    "TELEMETRY_UNAVAILABLE", "Prediction could not be durably recorded"
                ) from exc
            logger.info(
                "prediction_recorded",
                extra={
                    "context": {
                        "request_id": request_id,
                        "prediction_id": event.id,
                        "model": loaded.name,
                        "version": loaded.version,
                        "predicted_class": event.predicted_class,
                        "inference_ms": event.inference_ms,
                    }
                },
            )
            return PredictionResponse(
                prediction_id=event.id,
                request_id=request_id,
                model=loaded.name,
                version=loaded.version,
                probability=probability,
                predicted_class=event.predicted_class,
                threshold=loaded.threshold,
            )
        finally:
            self.capacity.release()

    def label(self, event_id: str, actual: int, request_id: str) -> dict:
        try:
            with self.factory.begin() as session:
                event = session.scalar(
                    select(PredictionEvent).where(PredictionEvent.id == event_id).with_for_update()
                )
                if event is None:
                    raise ServingError(
                        "PREDICTION_NOT_FOUND", "Prediction event does not exist", 404
                    )
                if event.actual_label is not None and event.actual_label != actual:
                    raise ServingError(
                        "LABEL_CONFLICT", "A different label is already recorded", 409
                    )
                if event.actual_label is None:
                    event.actual_label, event.labeled_at = actual, now()
                    session.add(
                        AuditEvent(
                            actor=self.settings.actor,
                            action="prediction.labeled",
                            resource_type="prediction",
                            resource_id=event_id,
                            details={"actual_label": actual, "request_id": request_id},
                        )
                    )
                return {"prediction_id": event_id, "actual_label": actual, "status": "recorded"}
        except SQLAlchemyError as exc:
            raise ServingError(
                "DATABASE_UNAVAILABLE", "Labels cannot be persisted right now"
            ) from exc

    def summary(self) -> dict:
        if self.loaded is None:
            raise ServingError("MODEL_NOT_LOADED", "No model is loaded")
        cutoff = now() - timedelta(seconds=self.settings.metrics_window_seconds)
        with self.factory() as session:
            groups = session.execute(
                select(PredictionEvent.predicted_class, PredictionEvent.actual_label, func.count())
                .where(
                    PredictionEvent.model_version_id == self.loaded.version_id,
                    PredictionEvent.created_at >= cutoff,
                )
                .group_by(PredictionEvent.predicted_class, PredictionEvent.actual_label)
            ).all()
        total = sum(count for _, _, count in groups)
        labeled = sum(count for _, actual, count in groups if actual is not None)
        counts = {(predicted, actual): count for predicted, actual, count in groups}
        tp, fp = counts.get((1, 1), 0), counts.get((1, 0), 0)
        fn, tn = counts.get((0, 1), 0), counts.get((0, 0), 0)

        def ratio(a, b):
            return a / b if b else None

        outcome = "failure" if self.loaded.target == "failure" else "fraud"
        return {
            "model": self.loaded.name,
            "version": self.loaded.version,
            "window_seconds": self.settings.metrics_window_seconds,
            "predictions": total,
            "labeled": labeled,
            "label_coverage": ratio(labeled, total),
            f"predicted_{outcome}_rate": ratio(sum(c for p, _, c in groups if p == 1), total),
            f"observed_{outcome}_rate": ratio(tp + fn, labeled),
            "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, tp + fn),
            "f1": ratio(2 * tp, 2 * tp + fp + fn),
            "false_positive_rate": ratio(fp, fp + tn),
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        }
