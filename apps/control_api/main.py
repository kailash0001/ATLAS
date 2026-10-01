import asyncio
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from aegis.core.errors import AegisError
from aegis.db.session import make_engine, sessions
from aegis.deployment.config import ControlSettings
from aegis.deployment.service import DeploymentService
from aegis.investigation.service import InvestigationService
from aegis.registry.queries import Queries
from aegis.reliability.policy import load_policy as quality_policy
from aegis.reliability.service import ReliabilityService
from aegis.remediation.policy import load_policy as gate_policy
from aegis.remediation.service import RemediationService
from apps.control_api.queries import monitoring, snapshot


class Reason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=2000)


class Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: dict[str, float | str]


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actual: float = Field(allow_inf_nan=False)


class Retrain(Reason):
    model: str
    baseline: int = Field(ge=1)
    dataset_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    algorithm: str
    verification_id: UUID
    investigation_id: UUID | None = None


def create_app(settings=None, factory=None, deployments=None):
    settings = settings or ControlSettings()
    engine = None if factory else make_engine(settings.database_url)
    factory = factory or sessions(engine)
    deployments = deployments or DeploymentService(settings, factory)
    remediation = RemediationService(settings, factory)
    reliability = ReliabilityService(factory, settings.actor)
    investigations = InvestigationService(factory, settings.actor)

    async def controller():
        while True:
            try:
                await run_in_threadpool(deployments.tick)
            except Exception:
                import logging

                logging.getLogger("aegis.controller").exception("Controller iteration unavailable")
            await asyncio.sleep(10)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(controller()) if settings.controller_enabled else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if engine:
            engine.dispose()

    app = FastAPI(title="ATLAS Control API", version="0.6.0", lifespan=lifespan)
    app.state.deployments = deployments

    def authorize(authorization: str = Header(default="")):
        if not settings.control_token or not hmac.compare_digest(
            authorization, "Bearer " + settings.control_token
        ):
            raise HTTPException(401, "A configured operator token is required")

    @app.exception_handler(AegisError)
    async def domain_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        with factory() as session:
            if session.execute(text("SELECT version_num FROM alembic_version")).scalar() != "0006":
                raise HTTPException(503, "Apply database migration 0006")
        return {"status": "ready", "environment": settings.environment}

    @app.get("/api/v1/state")
    def state():
        return snapshot(factory, settings)

    @app.get("/api/v1/monitoring")
    def metrics():
        return monitoring(settings)

    @app.get("/api/v1/models/{name}")
    def model(name: str):
        return Queries(factory).inspect_model(name)

    @app.post("/api/v1/incidents/{incident_id}/{action}", dependencies=[Depends(authorize)])
    def incident_action(incident_id: UUID, action: str, body: Reason):
        if action == "investigate":
            return investigations.investigate(str(incident_id))
        status = {"acknowledge": "ACKNOWLEDGED", "resolve": "RESOLVED"}.get(action)
        if not status:
            raise HTTPException(404)
        return reliability.transition(str(incident_id), status, body.reason)

    @app.post("/api/v1/retraining", dependencies=[Depends(authorize)])
    def retrain(body: Retrain):
        from aegis.reliability.workload import context

        config, _, _ = context(settings, factory, body.model, body.baseline)
        workload = {"is_fraud": "fraud", "failure": "maintenance", "demand_kw": "energy"}[
            config.target
        ]
        return remediation.create(
            body.model,
            body.baseline,
            settings.data_root / config.dataset.name / body.dataset_fingerprint,
            body.algorithm,
            gate_policy(Path("configs/remediation/default.yaml")),
            quality_policy(Path(f"configs/reliability/{workload}.yaml")),
            str(body.verification_id),
            body.reason,
            str(body.investigation_id) if body.investigation_id else None,
        )

    @app.post("/api/v1/pipelines/{request_id}/{action}", dependencies=[Depends(authorize)])
    def pipeline_action(request_id: UUID, action: str, body: Reason):
        if action in {"approve", "reject"}:
            return remediation.decide(str(request_id), action == "approve", body.reason)
        if action == "deploy":
            return deployments.create(str(request_id), body.reason)
        if action == "run":
            from aegis.deployment.automation import schedule

            return schedule(settings, factory, str(request_id))
        raise HTTPException(404)

    @app.post("/api/v1/deployments/{deployment_id}/{action}", dependencies=[Depends(authorize)])
    def deployment_action(deployment_id: UUID, action: str, body: Reason):
        if action == "advance":
            return deployments.advance(str(deployment_id), body.reason)
        if action == "rollback":
            return deployments.rollback(str(deployment_id), body.reason)
        if action == "observe":
            return deployments.observe(str(deployment_id))
        raise HTTPException(404)

    @app.post("/api/v1/predict/{model}")
    def predict(model: str, body: Prediction):
        return deployments.predict(model, body.features)

    @app.post("/api/v1/labels/{event_id}", dependencies=[Depends(authorize)])
    def label(event_id: UUID, body: Label):
        return deployments.label(str(event_id), body.actual)

    return app
