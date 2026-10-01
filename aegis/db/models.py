from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Model(Base):
    __tablename__ = "models"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    owner: Mapped[str] = mapped_column(String(200))
    use_case: Mapped[str] = mapped_column(String(200))
    risk_level: Mapped[str] = mapped_column(String(20))
    environment: Mapped[str] = mapped_column(String(30))
    registry_name: Mapped[str] = mapped_column(String(100), unique=True)
    sync_pending: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    source: Mapped[str] = mapped_column(Text)


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    manifest: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TrainingRun(Base):
    __tablename__ = "training_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id"), index=True)
    dataset_version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"), index=True)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    mlflow_experiment_id: Mapped[str | None] = mapped_column(String(64))
    algorithm: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="RUNNING", index=True)
    config: Mapped[dict] = mapped_column(JSON)
    code_revision: Mapped[str] = mapped_column(String(100))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('RUNNING','FINISHED','FAILED')"),)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id"), index=True)
    training_run_id: Mapped[str] = mapped_column(ForeignKey("training_runs.id"), unique=True)
    version: Mapped[int] = mapped_column(Integer)
    framework: Mapped[str] = mapped_column(String(80), default="scikit-learn")
    status: Mapped[str] = mapped_column(String(20), default="candidate", index=True)
    model_uri: Mapped[str] = mapped_column(Text)
    features: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("model_id", "version"),
        CheckConstraint("status IN ('candidate','champion','archived','rejected')"),
        Index(
            "uq_one_champion",
            "model_id",
            unique=True,
            postgresql_where=text("status = 'champion'"),
            sqlite_where=text("status = 'champion'"),
        ),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(100), index=True)
    details: Mapped[dict] = mapped_column("metadata", JSON)


class PredictionEvent(Base):
    __tablename__ = "prediction_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    model_version_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    features: Mapped[dict] = mapped_column(JSON)
    probability: Mapped[float] = mapped_column(Float)
    predicted_class: Mapped[int] = mapped_column(Integer)
    threshold: Mapped[float] = mapped_column(Float)
    inference_ms: Mapped[float] = mapped_column(Float)
    actual_label: Mapped[int | None] = mapped_column(Integer)
    labeled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("probability >= 0 AND probability <= 1"),
        CheckConstraint("threshold > 0 AND threshold < 1"),
        CheckConstraint("predicted_class IN (0, 1)"),
        CheckConstraint("actual_label IS NULL OR actual_label IN (0, 1)"),
        CheckConstraint("inference_ms >= 0"),
        CheckConstraint(
            "(actual_label IS NULL AND labeled_at IS NULL) OR "
            "(actual_label IS NOT NULL AND labeled_at IS NOT NULL)"
        ),
        Index("ix_prediction_version_time", "model_version_id", "created_at"),
    )


class ReliabilityReport(Base):
    __tablename__ = "reliability_reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    model_version_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    severity: Mapped[str] = mapped_column(String(20))
    evidence: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (
        CheckConstraint("severity IN ('HEALTHY','INFO','WARNING','HIGH','CRITICAL')"),
    )


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    model_version_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"), index=True)
    incident_type: Mapped[str] = mapped_column(String(40))
    feature: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    first_report_id: Mapped[str] = mapped_column(ForeignKey("reliability_reports.id"))
    latest_report_id: Mapped[str] = mapped_column(ForeignKey("reliability_reports.id"))
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED')"),
        CheckConstraint("severity IN ('WARNING','HIGH','CRITICAL')"),
        CheckConstraint("occurrences >= 1"),
        Index(
            "uq_active_incident",
            "model_version_id",
            "incident_type",
            "feature",
            unique=True,
            postgresql_where=text("status != 'RESOLVED'"),
            sqlite_where=text("status != 'RESOLVED'"),
        ),
    )


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("reliability_reports.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    rules_version: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(30))
    evidence: Mapped[dict] = mapped_column(JSON)
    conclusion: Mapped[dict] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        CheckConstraint(
            "category IN ('DATA','MODEL','INFRASTRUCTURE','UPSTREAM_SYSTEM','DEPLOYMENT','UNKNOWN')"
        ),
    )


class InvestigationExplanation(Base):
    __tablename__ = "investigation_explanations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    model: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint("status IN ('ACCEPTED','UNAVAILABLE','REJECTED')"),)


class VerificationRun(Base):
    __tablename__ = "verification_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    results: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RetrainingRequest(Base):
    __tablename__ = "retraining_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id"), index=True)
    baseline_version_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    candidate_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_versions.id"), unique=True
    )
    investigation_id: Mapped[str | None] = mapped_column(ForeignKey("investigations.id"))
    verification_id: Mapped[str] = mapped_column(ForeignKey("verification_runs.id"))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="REQUESTED", index=True)
    requested_by: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    dataset_path: Mapped[str] = mapped_column(Text)
    dataset_fingerprint: Mapped[str] = mapped_column(String(64))
    source_hash: Mapped[str] = mapped_column(String(64))
    algorithm: Mapped[str] = mapped_column(String(80))
    config: Mapped[dict] = mapped_column(JSON)
    policy: Mapped[dict] = mapped_column(JSON)
    quality_policy: Mapped[dict] = mapped_column(JSON)
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        CheckConstraint(
            "status IN ('REQUESTED','VALIDATING','VALIDATED',"
            "'TRAINING','TRAINED','EVALUATING','AWAITING_APPROVAL','APPROVED','REJECTED','FAILED')"
        ),
    )


class RetrainingAttempt(Base):
    __tablename__ = "retraining_attempts"
    request_id: Mapped[str] = mapped_column(ForeignKey("retraining_requests.id"), primary_key=True)
    training_run_id: Mapped[str] = mapped_column(ForeignKey("training_runs.id"), unique=True)


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("retraining_requests.id"), unique=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    previous_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    environment: Mapped[str] = mapped_column(String(30))
    backend: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="PREPARING", index=True)
    traffic_percent: Mapped[int] = mapped_column(Integer, default=0)
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    policy: Mapped[dict] = mapped_column(JSON)
    health: Mapped[dict] = mapped_column(JSON, default=dict)
    initiated_by: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    stage_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("traffic_percent IN (0,10,25,50,100)"),
        CheckConstraint("backend IN ('native','kubernetes')"),
        CheckConstraint(
            "status IN ('PREPARING','CANARY','PROMOTED','ROLLED_BACK','FAILED','SUPERSEDED')"
        ),
        Index(
            "uq_active_deployment",
            "model_id",
            unique=True,
            postgresql_where=text("status IN ('PREPARING','CANARY','PROMOTED')"),
            sqlite_where=text("status IN ('PREPARING','CANARY','PROMOTED')"),
        ),
    )


class RoutingEvent(Base):
    __tablename__ = "routing_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    deployment_id: Mapped[str] = mapped_column(ForeignKey("deployments.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    epoch: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    success: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[float] = mapped_column(Float)
    prediction: Mapped[float | None] = mapped_column(Float)
    actual: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        CheckConstraint("latency_ms >= 0"),
        Index("ix_routing_deployment_epoch", "deployment_id", "epoch", "created_at"),
    )
