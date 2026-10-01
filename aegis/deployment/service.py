import math
import secrets
import time

from mlflow import MlflowClient
from sqlalchemy import select

from aegis.core.errors import AegisError
from aegis.db.models import (
    AuditEvent,
    Deployment,
    Model,
    ModelVersion,
    RetrainingRequest,
    RoutingEvent,
    TrainingRun,
    now,
)
from aegis.deployment.backends import Backends
from aegis.deployment.config import RolloutPolicy, load_policy
from aegis.deployment.health import evaluate
from aegis.deployment.runtime import Runtime
from aegis.registry.service import GovernanceService
from aegis.reliability.service import serialize
from aegis.remediation.service import deployment_eligible


def audit(session, actor, row, action, **details):
    session.add(
        AuditEvent(
            actor=actor,
            action=f"deployment.{action}",
            resource_type="deployment",
            resource_id=row.id,
            details=details,
        )
    )


class DeploymentService:
    def __init__(self, settings, factory, backends=None):
        self.settings, self.factory = settings, factory
        self.runtime = Runtime(settings, factory)
        self.backends = backends or Backends(settings, self.runtime)

    def list(self):
        with self.factory() as session:
            return [
                serialize(r)
                for r in session.scalars(
                    select(Deployment).order_by(Deployment.started_at.desc()).limit(100)
                )
            ]

    def lock(self, session, deployment_id):
        model_id = session.scalar(select(Deployment.model_id).where(Deployment.id == deployment_id))
        if model_id is None:
            raise AegisError("Unknown deployment")
        session.scalar(select(Model).where(Model.id == model_id).with_for_update())
        return session.scalar(
            select(Deployment).where(Deployment.id == deployment_id).with_for_update()
        )

    def create(self, request_id, reason, automatic=False):
        if not reason.strip():
            raise AegisError("A deployment reason is required")
        policy = load_policy(self.settings.rollout_policy)
        if policy.autonomy_level < (3 if automatic else 1):
            raise AegisError("Autonomy policy does not permit starting a canary")
        with self.factory.begin() as session:
            request = session.get(RetrainingRequest, request_id)
            if request is None:
                raise AegisError("Unknown retraining request")
            model = session.scalar(
                select(Model).where(Model.id == request.model_id).with_for_update()
            )
            existing = session.scalar(select(Deployment).where(Deployment.request_id == request_id))
            if existing:
                return serialize(existing)
            deployment_eligible(session, request)
            active = session.scalar(
                select(Deployment).where(
                    Deployment.model_id == model.id,
                    Deployment.status.in_(["PREPARING", "CANARY", "PROMOTED"]),
                )
            )
            if active and active.status != "PROMOTED":
                raise AegisError("A rollout is already active")
            if active:
                if active.candidate_id != request.baseline_version_id:
                    raise AegisError("Request baseline is not the serving version")
                active.status = "SUPERSEDED"
                session.flush()
            row = Deployment(
                model_id=model.id,
                request_id=request.id,
                candidate_id=request.candidate_version_id,
                previous_id=request.baseline_version_id,
                environment=model.environment,
                backend=self.settings.deployment_backend,
                policy=policy.model_dump(),
                initiated_by=self.settings.actor,
                reason=reason,
            )
            session.add(row)
            session.flush()
            audit(session, self.settings.actor, row, "started", reason=reason, backend=row.backend)
            snapshot = serialize(row)
        try:
            self.backends.prepare(snapshot["backend"], snapshot["previous_id"])
            self.backends.prepare(snapshot["backend"], snapshot["candidate_id"])
            with self.factory.begin() as session:
                row = self.lock(session, snapshot["id"])
                if row.status != "PREPARING":
                    raise AegisError("Deployment preparation was cancelled")
                deployment_eligible(session, session.get(RetrainingRequest, request_id))
                row.status, row.traffic_percent, row.stage_started_at = "CANARY", 10, now()
                audit(session, self.settings.actor, row, "traffic.changed", percent=10)
                return serialize(row)
        except Exception as exc:
            with self.factory.begin() as session:
                row = self.lock(session, snapshot["id"])
                if row.status == "PREPARING":
                    row.status, row.completed_at = "FAILED", now()
                    audit(session, self.settings.actor, row, "failed", error=type(exc).__name__)
            raise

    def sync(self, model_id):
        with self.factory() as session:
            model = session.get(Model, model_id)
            name = model.name
        try:
            GovernanceService(
                self.factory,
                MlflowClient(tracking_uri=self.settings.mlflow_tracking_uri),
                self.settings.actor,
            ).sync(name)
        except Exception:
            # SQL routing is authoritative. A failed registry sync stays visibly pending.
            return False
        return True

    def _rollback(self, session, row, reason):
        model = session.get(Model, row.model_id)
        candidate = session.get(ModelVersion, row.candidate_id)
        previous = session.get(ModelVersion, row.previous_id)
        if row.status == "PROMOTED":
            candidate.status = "archived"
            session.flush()
            previous.status = "champion"
            model.sync_pending = True
        row.status, row.traffic_percent, row.completed_at = "ROLLED_BACK", 0, now()
        row.epoch += 1
        row.stage_started_at = now()
        audit(
            session,
            self.settings.actor,
            row,
            "rolled_back",
            reason=reason,
            restored_version_id=previous.id,
        )

    def rollback(self, deployment_id, reason):
        if not reason.strip():
            raise AegisError("A rollback reason is required")
        with self.factory.begin() as session:
            row = self.lock(session, deployment_id)
            if row.status == "ROLLED_BACK":
                return serialize(row)
            if row.status not in {"PREPARING", "CANARY", "PROMOTED"}:
                raise AegisError("This deployment is no longer active")
            self._rollback(session, row, reason)
            result = serialize(row)
        self.sync(result["model_id"])
        return result

    def observe(self, deployment_id):
        rolled_back = False
        with self.factory.begin() as session:
            row = self.lock(session, deployment_id)
            if row.status not in {"CANARY", "PROMOTED"}:
                return serialize(row)
            row.health = evaluate(session, row)
            if row.health["status"] == "UNHEALTHY" and row.policy["auto_rollback"]:
                self._rollback(
                    session, row, "Automatic health failure: " + ", ".join(row.health["failures"])
                )
                rolled_back = True
            result = serialize(row)
        if rolled_back:
            self.sync(result["model_id"])
        return result

    def advance(self, deployment_id, reason, automatic=False):
        if not reason.strip():
            raise AegisError("A progression reason is required")
        snapshot = self.observe(deployment_id)
        self.backends.ready(snapshot["backend"], snapshot["candidate_id"])
        self.backends.ready(snapshot["backend"], snapshot["previous_id"])
        promoted = False
        with self.factory.begin() as session:
            row = self.lock(session, deployment_id)
            policy = RolloutPolicy.model_validate(row.policy)
            if policy.autonomy_level < (4 if automatic else 1):
                raise AegisError("Autonomy policy does not permit progression")
            if row.status != "CANARY" or row.epoch != snapshot["epoch"]:
                raise AegisError("Rollout changed or is not a canary")
            deployment_eligible(session, session.get(RetrainingRequest, row.request_id))
            health = evaluate(session, row)
            if health["status"] != "HEALTHY":
                raise AegisError(
                    "Fresh healthy traffic and required labels are needed before progression"
                )
            row.health = health
            if row.traffic_percent == 100:
                model = session.get(Model, row.model_id)
                champion = session.scalar(
                    select(ModelVersion).where(
                        ModelVersion.model_id == model.id, ModelVersion.status == "champion"
                    )
                )
                if champion:
                    champion.status = "archived"
                    session.flush()
                session.get(ModelVersion, row.candidate_id).status = "champion"
                model.sync_pending = True
                row.status, row.completed_at = "PROMOTED", now()
                audit(session, self.settings.actor, row, "promoted", health=health, reason=reason)
                promoted = True
            else:
                row.traffic_percent = {10: 25, 25: 50, 50: 100}[row.traffic_percent]
                row.epoch += 1
                row.stage_started_at = now()
                audit(
                    session,
                    self.settings.actor,
                    row,
                    "traffic.changed",
                    percent=row.traffic_percent,
                    health=health,
                    reason=reason,
                )
            result = serialize(row)
        if promoted:
            self.sync(result["model_id"])
        return result

    def predict(self, model_name, features):
        with self.factory() as session:
            row = session.scalar(
                select(Deployment)
                .join(Model)
                .where(Model.name == model_name, Deployment.status != "SUPERSEDED")
                .order_by(Deployment.started_at.desc())
                .limit(1)
            )
            if row is None:
                raise AegisError("No deployment is configured for this model")
            snapshot = serialize(row)
        candidate = secrets.randbelow(100) < snapshot["traffic_percent"]
        version_id = snapshot["candidate_id"] if candidate else snapshot["previous_id"]
        # Invalid client input is not a model-health failure.
        self.runtime.validate(version_id, features)
        started = time.perf_counter()
        prediction, error = None, None
        try:
            prediction = self.backends.predict(snapshot["backend"], version_id, features)
            if not math.isfinite(prediction):
                raise AegisError("Nonfinite prediction")
        except Exception as exc:
            error = type(exc).__name__
        elapsed = (time.perf_counter() - started) * 1000
        with self.factory.begin() as session:
            event = RoutingEvent(
                deployment_id=snapshot["id"],
                version_id=version_id,
                epoch=snapshot["epoch"],
                success=error is None,
                latency_ms=elapsed,
                prediction=prediction,
                error=error,
            )
            session.add(event)
            session.flush()
            event_id = event.id
        if error:
            raise AegisError("Prediction failed; failure recorded for rollout health")
        return {
            "event_id": event_id,
            "deployment_id": snapshot["id"],
            "version_id": version_id,
            "prediction": prediction,
            "candidate": candidate,
            "latency_ms": elapsed,
        }

    def label(self, event_id, actual):
        if not math.isfinite(actual):
            raise AegisError("Label must be finite")
        with self.factory.begin() as session:
            row = session.scalar(
                select(RoutingEvent).where(RoutingEvent.id == event_id).with_for_update()
            )
            if row is None or not row.success:
                raise AegisError("Unknown successful prediction")
            run = session.get(
                TrainingRun, session.get(ModelVersion, row.version_id).training_run_id
            )
            if run.config["target"] != "demand_kw" and actual not in {0, 1}:
                raise AegisError("Classification labels must be zero or one")
            if row.actual is not None:
                if row.actual != actual:
                    raise AegisError("Conflicting label")
                return serialize(row)
            row.actual = actual
            session.add(
                AuditEvent(
                    actor=self.settings.actor,
                    action="rollout.prediction.labeled",
                    resource_type="routing_event",
                    resource_id=row.id,
                    details={"actual": actual},
                )
            )
            return serialize(row)

    def tick(self):
        policy = load_policy(self.settings.rollout_policy)
        if policy.autonomy_level >= 2:
            from aegis.deployment.automation import schedule

            with self.factory() as session:
                requests = [
                    (r.id, r.status)
                    for r in session.scalars(
                        select(RetrainingRequest)
                        .where(RetrainingRequest.status.in_(["REQUESTED", "APPROVED"]))
                        .order_by(RetrainingRequest.created_at)
                        .limit(20)
                    )
                ]
            for request_id, status in requests:
                try:
                    if status == "REQUESTED" and self.settings.airflow_url:
                        schedule(self.settings, self.factory, request_id)
                    elif status == "APPROVED" and policy.autonomy_level >= 3:
                        self.create(request_id, "Policy-authorized approved canary", automatic=True)
                except Exception:
                    import logging

                    logging.getLogger("aegis.controller").exception("Automation action blocked")
        for row in self.list():
            if row["status"] in {"CANARY", "PROMOTED"}:
                try:
                    observed = self.observe(row["id"])
                    if (
                        observed["status"] == "CANARY"
                        and observed["health"].get("status") == "HEALTHY"
                        and observed["policy"]["autonomy_level"] >= 4
                    ):
                        self.advance(row["id"], "Policy-driven progressive rollout", automatic=True)
                except Exception:
                    import logging

                    logging.getLogger("aegis.controller").exception("Rollout observation failed")
