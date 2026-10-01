from dataclasses import replace
from datetime import timedelta
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from aegis.db.models import AuditEvent, Model, ModelVersion, PredictionEvent, TrainingRun, now
from aegis.serving.config import ServingSettings
from aegis.serving.loader import LoadedModel
from aegis.serving.service import InferenceService
from apps.inference.main import create_app
from tests.unit.test_governance import seed

PAYLOAD = {
    "amount": 25.0,
    "hour": 12,
    "distance_from_home": 5.0,
    "transactions_24h": 2,
    "account_age_days": 300,
    "merchant_category": "grocery",
    "card_present": "yes",
}


@pytest.fixture
def serving(database, config):
    seed(database)
    settings = ServingSettings(environment="test", max_request_bytes=1024)
    with database.begin() as session:
        model = session.scalar(select(Model))
        model.sync_pending = False
        candidate = session.scalar(select(ModelVersion).where(ModelVersion.version == 1))
        candidate.status, candidate.features = "champion", config.features.model_dump()
        run = session.get(TrainingRun, candidate.training_run_id)
        run.config = {"target": config.target, "training": {"threshold": 0.7}}
        predictor = MagicMock()
        predictor.predict.return_value = np.array([[0.4, 0.6]])
        loaded = LoadedModel(
            model.name,
            model.id,
            candidate.id,
            1,
            model.registry_name,
            0.7,
            tuple(config.features.numeric),
            tuple(config.features.all),
            predictor,
        )
    service = InferenceService(settings, database)
    service.loader.load = lambda: loaded
    return service


@pytest.fixture
def client(serving):
    with TestClient(create_app(serving.settings, serving)) as client:
        yield client


def test_prediction_lineage_threshold_and_no_label_leakage(client, serving, database):
    response = client.post("/api/v1/predict", json=PAYLOAD, headers={"X-Request-ID": "test-123"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["predicted_class"] == 0  # .6 probability is below saved threshold .7
    assert body["request_id"] == response.headers["x-request-id"] == "test-123"
    assert response.headers["x-model-version"] == "1"
    with database() as session:
        event = session.get(PredictionEvent, body["prediction_id"])
        assert event.model_version_id == serving.loaded.version_id
        assert event.features == PAYLOAD and event.actual_label is None
    summary = client.get("/api/v1/monitoring/summary").json()
    assert summary["predictions"] == 1 and summary["labeled"] == 0
    assert summary["recall"] is None and summary["f1"] is None
    assert client.get("/api/v1/model").json()["threshold"] == 0.7


@pytest.mark.parametrize(
    "changed",
    [
        {"hour": 24},
        {"amount": -1},
        {"is_fraud": 1},
        {"amount": "25"},
        {"card_present": "maybe"},
    ],
)
def test_invalid_requests_are_rejected_and_not_recorded(client, database, changed):
    response = client.post("/api/v1/predict", json={**PAYLOAD, **changed})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    with database() as session:
        assert session.scalar(select(func.count()).select_from(PredictionEvent)) == 0


def test_missing_values_and_unknown_merchant_allowed(client):
    response = client.post(
        "/api/v1/predict", json={**PAYLOAD, "hour": None, "merchant_category": "new"}
    )
    assert response.status_code == 200
    missing = PAYLOAD.copy()
    missing.pop("amount")
    assert client.post("/api/v1/predict", json=missing).status_code == 422


def test_labels_are_idempotent_audited_and_conflicts_fail(client, database):
    result = client.post("/api/v1/predict", json=PAYLOAD).json()
    path = f"/api/v1/predictions/{result['prediction_id']}/label"
    assert client.put(path, json={"actual_label": 1}).status_code == 200
    assert client.put(path, json={"actual_label": 1}).status_code == 200
    assert client.put(path, json={"actual_label": 0}).status_code == 409
    assert client.put(path, json={"actual_label": True}).status_code == 422
    summary = client.get("/api/v1/monitoring/summary").json()
    assert summary["labeled"] == 1 and summary["confusion"]["fn"] == 1
    assert summary["recall"] == 0 and summary["f1"] == 0
    with database() as session:
        events = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "prediction.labeled")
        )
        assert len(list(events)) == 1


def test_real_confusion_calculation_window_and_restart(client, serving, database):
    with database.begin() as session:
        for predicted, actual in [(1, 1), (1, 0), (0, 1), (0, 0)]:
            session.add(
                PredictionEvent(
                    request_id="fixture",
                    model_version_id=serving.loaded.version_id,
                    features={},
                    probability=float(predicted),
                    predicted_class=predicted,
                    threshold=0.7,
                    inference_ms=1,
                    actual_label=actual,
                    labeled_at=now(),
                )
            )
        session.add(
            PredictionEvent(
                request_id="old",
                model_version_id=serving.loaded.version_id,
                features={},
                probability=1,
                predicted_class=1,
                threshold=0.7,
                inference_ms=1,
                created_at=now() - timedelta(days=2),
            )
        )
    summary = serving.summary()
    assert summary["predictions"] == summary["labeled"] == 4
    assert summary["precision"] == summary["recall"] == summary["f1"] == 0.5
    assert summary["false_positive_rate"] == 0.5
    restarted = InferenceService(serving.settings, database)
    restarted.loaded = serving.loaded
    assert restarted.summary() == summary


def test_governance_changes_make_service_unready(client, database):
    assert client.get("/health/ready").status_code == 200
    with database.begin() as session:
        session.scalar(select(Model)).sync_pending = True
    assert client.get("/health/live").status_code == 200
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REGISTRY_SYNC_PENDING"
    assert client.post("/api/v1/predict", json=PAYLOAD).status_code == 503


def test_unavailable_model_is_live_but_not_ready(database):
    service = InferenceService(ServingSettings(environment="test"), database)
    with TestClient(create_app(service.settings, service)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        metrics = client.get("/metrics").text
        assert "aegis_serving_ready 0.0" in metrics
        assert "aegis_business_metrics_available 0.0" in metrics


def test_prediction_or_persistence_failure_returns_no_success(client, serving, monkeypatch):
    serving.loaded.predictor.predict.return_value = np.array([[np.nan, 0.5]])
    assert client.post("/api/v1/predict", json=PAYLOAD).status_code == 500
    serving.loaded.predictor.predict.return_value = np.array([[0.5, 0.5]])

    def offline():
        raise OperationalError("insert", None, Exception("offline"))

    monkeypatch.setattr(serving.factory, "begin", offline)
    response = client.post("/api/v1/predict", json=PAYLOAD)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "TELEMETRY_UNAVAILABLE"


def test_bounded_metrics_payload_and_error_request_ids(client):
    assert client.post("/api/v1/predict", content=b"x" * 2048).status_code == 413
    client.get("/nonexistent/private-id-123")
    client.post("/api/v1/predict", json=PAYLOAD)
    response = client.post("/api/v1/predict", json={"bad": "private-input"})
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]
    assert "private-input" not in response.text
    metrics = client.get("/metrics").text
    assert "private-id-123" not in metrics
    assert 'route="unmatched"' in metrics
    assert 'status="422"' in metrics and 'status="200"' in metrics
    assert "aegis_http_request_duration_seconds_bucket" in metrics
    assert "aegis_predictions_total" in metrics
    assert "aegis_process_cpu_seconds_total" in metrics


def test_overload_is_explicit(client, serving):
    for _ in range(serving.settings.serving_max_concurrency):
        serving.capacity.acquire()
    response = client.post("/api/v1/predict", json=PAYLOAD)
    assert response.status_code == 429


def test_stale_champion_and_unknown_label(client, serving):
    serving.loaded = replace(serving.loaded, version_id="old")
    assert client.get("/health/ready").status_code == 503
    response = client.put(
        "/api/v1/predictions/00000000-0000-0000-0000-000000000000/label", json={"actual_label": 0}
    )
    assert response.status_code == 404
