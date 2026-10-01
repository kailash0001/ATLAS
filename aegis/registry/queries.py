from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, sessionmaker

from aegis.core.errors import GovernanceError
from aegis.db.models import AuditEvent, DatasetVersion, Deployment, Model, ModelVersion, TrainingRun
from aegis.registry.service import find_model


def record(row) -> dict:
    return {column.key: getattr(row, column.key) for column in inspect(row).mapper.column_attrs}


class Queries:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def models(self) -> list[dict]:
        with self.sessions() as session:
            return [record(m) for m in session.scalars(select(Model).order_by(Model.name))]

    def inspect_model(self, name: str) -> dict:
        with self.sessions() as session:
            model = find_model(session, name)
            versions = []
            for item in session.scalars(
                select(ModelVersion)
                .where(ModelVersion.model_id == model.id)
                .order_by(ModelVersion.version.desc())
            ):
                run = session.get(TrainingRun, item.training_run_id)
                dataset = session.get(DatasetVersion, run.dataset_version_id)
                versions.append(
                    {
                        **record(item),
                        "metrics": run.metrics,
                        "algorithm": run.algorithm,
                        "mlflow_run_id": run.mlflow_run_id,
                        "experiment_id": run.mlflow_experiment_id,
                        "dataset_fingerprint": dataset.fingerprint,
                        "code_revision": run.code_revision,
                    }
                )
            return {
                **record(model),
                "versions": versions,
                "deployment_history": [
                    record(d)
                    for d in session.scalars(
                        select(Deployment)
                        .where(Deployment.model_id == model.id)
                        .order_by(Deployment.started_at.desc())
                    )
                ],
            }

    def runs(self, name: str | None, limit: int = 50) -> list[dict]:
        with self.sessions() as session:
            query = select(TrainingRun)
            if name:
                query = query.where(TrainingRun.model_id == find_model(session, name).id)
            return [
                record(r)
                for r in session.scalars(query.order_by(TrainingRun.started_at.desc()).limit(limit))
            ]

    def compare(self, name: str, metric: str = "validation_f1") -> list[dict]:
        if not metric.startswith("validation_"):
            raise GovernanceError(
                "Rank candidates on validation metrics; reserve test metrics for reporting"
            )
        versions = self.inspect_model(name)["versions"]
        if versions and any(metric not in v["metrics"] for v in versions):
            raise GovernanceError(f"Metric unavailable: {metric}")
        fingerprints = {v["dataset_fingerprint"] for v in versions}
        if len(fingerprints) > 1:
            raise GovernanceError(
                "Versions use different datasets; evaluate on a common dataset first"
            )
        ascending = metric in {
            "validation_false_positive_rate",
            "validation_mae",
            "validation_rmse",
            "validation_mape_percent",
        }
        allowed = {
            "validation_f1",
            "validation_recall",
            "validation_precision",
            "validation_roc_auc",
            "validation_average_precision",
            "validation_false_positive_rate",
            "validation_mae",
            "validation_rmse",
            "validation_mape_percent",
        }
        if metric not in allowed:
            raise GovernanceError(f"Unsupported ranking metric: {metric}")
        return sorted(versions, key=lambda v: v["metrics"][metric], reverse=not ascending)

    def audit(self, limit: int = 50) -> list[dict]:
        with self.sessions() as session:
            return [
                record(e)
                for e in session.scalars(
                    select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(limit)
                )
            ]
