import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import event
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from aegis.core.logging import configure_logging
from aegis.db.session import make_engine, sessions
from aegis.serving.config import ServingSettings
from aegis.serving.errors import ServingError
from aegis.serving.metrics import ServingMetrics
from aegis.serving.schemas import (
    ErrorResponse,
    FraudFeatures,
    LabelRequest,
    MaintenanceFeatures,
    PredictionResponse,
)
from aegis.serving.service import InferenceService
from apps.inference.middleware import RequestMiddleware

logger = logging.getLogger("aegis.serving")


def create_app(settings: ServingSettings | None = None, service: InferenceService | None = None):
    settings = settings or ServingSettings()
    engine = None
    if service is None:
        engine = make_engine(settings.database_url)
        if engine.dialect.name == "postgresql":

            @event.listens_for(engine, "connect")
            def bounded_queries(connection, _):
                timeout_ms = settings.serving_database_timeout_seconds * 1000
                with connection.cursor() as cursor:
                    cursor.execute(f"SET statement_timeout = {timeout_ms}")
                    cursor.execute(f"SET lock_timeout = {timeout_ms}")
                connection.commit()

        service = InferenceService(settings, sessions(engine))
    metrics = ServingMetrics(service)

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        await run_in_threadpool(service.start)
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="AegisML Inference",
        version="0.3.0",
        lifespan=lifespan,
        description="Governed local inference. Predictions are recorded before success. "
        "Labels are delayed ground truth, not model-generated outcomes.",
    )
    app.state.service, app.state.metrics = service, metrics
    app.add_middleware(RequestMiddleware, metrics=metrics, max_bytes=settings.max_request_bytes)

    def error(request, code, message, status):
        return JSONResponse(
            {"error": {"code": code, "message": message, "request_id": request.state.request_id}},
            status_code=status,
        )

    @app.exception_handler(ServingError)
    async def serving_error(request: Request, exc: ServingError):
        logger.warning(
            "serving_error",
            extra={"context": {"request_id": request.state.request_id, "error_code": exc.code}},
        )
        return error(request, exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Do not echo financial inputs or arbitrary request bodies in errors/logs.
        return error(
            request, "INVALID_REQUEST", "Request does not match the documented schema", 422
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error(request, "HTTP_ERROR", "Requested operation is unavailable", exc.status_code)

    @app.get("/health/live", tags=["Health"])
    def live():
        return {"status": "alive"}

    @app.get("/health/ready", tags=["Health"], responses={503: {"model": ErrorResponse}})
    def ready():
        loaded = service.ready()
        return {"status": "ready", "model": loaded.name, "version": loaded.version}

    @app.post(
        "/api/v1/predict",
        response_model=PredictionResponse,
        tags=["Inference"],
        responses={
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            429: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    def predict(
        features: FraudFeatures | MaintenanceFeatures, request: Request, response: Response
    ):
        prediction = service.predict(features, request.state.request_id)
        response.headers["X-Model-Name"] = prediction.model
        response.headers["X-Model-Version"] = str(prediction.version)
        metrics.predictions.labels(
            prediction.model, str(prediction.version), str(prediction.predicted_class)
        ).inc()
        metrics.probabilities.labels(prediction.model, str(prediction.version)).observe(
            prediction.probability
        )
        return prediction

    @app.put(
        "/api/v1/predictions/{prediction_id}/label",
        tags=["Ground truth"],
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def label(prediction_id: UUID, body: LabelRequest, request: Request):
        return service.label(str(prediction_id), body.actual_label, request.state.request_id)

    @app.get("/api/v1/model", tags=["Model"])
    def model():
        loaded = service.ready()
        return {
            "name": loaded.name,
            "version": loaded.version,
            "registry_name": loaded.registry_name,
            "threshold": loaded.threshold,
            "features": loaded.feature_names,
            "reload_policy": "restart",
        }

    @app.get("/api/v1/monitoring/summary", tags=["Monitoring"])
    def summary():
        service.ready()
        return service.summary()

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return app
