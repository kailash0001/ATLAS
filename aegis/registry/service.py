from mlflow import MlflowClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aegis.core.errors import GovernanceError, NotFoundError
from aegis.db.models import AuditEvent, Model, ModelVersion, TrainingRun


def audit(session: Session, actor: str, action: str, resource_id: str, **details) -> None:
    session.add(
        AuditEvent(
            actor=actor,
            action=action,
            resource_type="model",
            resource_id=resource_id,
            details=details,
        )
    )


def find_model(session: Session, name: str, *, lock: bool = False) -> Model:
    query = select(Model).where(Model.name == name)
    if lock:
        query = query.with_for_update()
    model = session.scalar(query)
    if model is None:
        raise NotFoundError(f"Unknown model: {name}")
    return model


class GovernanceService:
    def __init__(self, sessions: sessionmaker[Session], client: MlflowClient, actor: str):
        self.sessions, self.client, self.actor = sessions, client, actor

    def transition(self, name: str, version: int, action: str, reason: str) -> None:
        if not reason.strip():
            raise GovernanceError("A nonempty reason is required")
        with self.sessions.begin() as session:
            model = find_model(session, name, lock=True)
            target = session.scalar(
                select(ModelVersion).where(
                    ModelVersion.model_id == model.id, ModelVersion.version == version
                )
            )
            if target is None:
                raise NotFoundError(f"Unknown version: {name}/{version}")
            run = session.get(TrainingRun, target.training_run_id)
            if run.status != "FINISHED":
                raise GovernanceError("Only successfully completed runs are eligible")
            next_status = {"promote": "champion", "reject": "rejected", "archive": "archived"}
            if action not in next_status:
                raise GovernanceError(f"Unknown governance action: {action}")
            if target.status == next_status[action]:
                return
            from aegis.db.models import Deployment

            if session.scalar(
                select(Deployment.id).where(
                    Deployment.model_id == model.id,
                    Deployment.status.in_(["PREPARING", "CANARY", "PROMOTED"]),
                )
            ):
                raise GovernanceError(
                    "Use the active deployment's progression or rollback controls"
                )
            allowed = {
                "promote": {"candidate"},
                "reject": {"candidate"},
                "archive": {"candidate", "rejected"},
            }
            if target.status not in allowed[action]:
                raise GovernanceError(f"Cannot {action} a {target.status} version")
            previous = target.status
            if action == "promote":
                from aegis.db.models import RetrainingAttempt, RetrainingRequest
                from aegis.remediation.service import deployment_eligible

                attempt = session.scalar(
                    select(RetrainingAttempt).where(RetrainingAttempt.training_run_id == run.id)
                )
                if attempt is not None:
                    deployment_eligible(session, session.get(RetrainingRequest, attempt.request_id))
                champion = session.scalar(
                    select(ModelVersion).where(
                        ModelVersion.model_id == model.id, ModelVersion.status == "champion"
                    )
                )
                if champion:
                    champion.status = "archived"
                    audit(
                        session,
                        self.actor,
                        "model.archived",
                        model.id,
                        version=champion.version,
                        reason="Replaced by champion",
                        replacement=version,
                    )
                    session.flush()
            target.status = next_status[action]
            model.sync_pending = True
            audit(
                session,
                self.actor,
                f"model.{next_status[action]}",
                model.id,
                version=version,
                previous_status=previous,
                reason=reason,
            )

    def sync(self, name: str) -> None:
        """SQL is authoritative; failed remote writes leave a durable pending flag.

        Hold the same model row lock as transitions so concurrent sync cannot publish
        stale aliases. Retrying applies the desired state idempotently.
        """
        with self.sessions.begin() as session:
            model = find_model(session, name, lock=True)
            versions = list(
                session.scalars(
                    select(ModelVersion)
                    .where(ModelVersion.model_id == model.id)
                    .order_by(ModelVersion.version.desc())
                )
            )
            if not versions:
                return
            registered = self.client.get_registered_model(model.registry_name)
            for alias in ("champion", "candidate"):
                desired = next((v for v in versions if v.status == alias), None)
                if desired:
                    self.client.set_registered_model_alias(
                        model.registry_name, alias, str(desired.version)
                    )
                elif alias in registered.aliases:
                    self.client.delete_registered_model_alias(model.registry_name, alias)
            for version in versions:
                self.client.set_model_version_tag(
                    model.registry_name, str(version.version), "aegis.status", version.status
                )
            if model.sync_pending:
                audit(session, self.actor, "registry.synced", model.id)
            model.sync_pending = False
