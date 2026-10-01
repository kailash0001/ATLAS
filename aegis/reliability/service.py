import json

from sqlalchemy import select

from aegis.core.errors import AegisError
from aegis.data.fraud import canonical, digest
from aegis.db.models import AuditEvent, Incident, ModelVersion, ReliabilityReport, now
from aegis.reliability.policy import highest


def serialize(row):
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


class ReliabilityService:
    def __init__(self, factory, actor):
        self.factory, self.actor = factory, actor

    def save(self, version_id: str, evidence: dict) -> dict:
        # Validate JSON before opening the transaction; reject NaN/Infinity evidence.
        json.dumps(evidence, allow_nan=False)
        fingerprint = digest(canonical({"version": version_id, "evidence": evidence}))
        with self.factory.begin() as session:
            # Serializes report/incident upserts per immutable model version on PostgreSQL.
            version = session.scalar(
                select(ModelVersion).where(ModelVersion.id == version_id).with_for_update()
            )
            if version is None:
                raise AegisError("Unknown model version")
            existing = session.scalar(
                select(ReliabilityReport).where(ReliabilityReport.fingerprint == fingerprint)
            )
            if existing:
                return serialize(existing)
            report = ReliabilityReport(
                model_version_id=version_id,
                fingerprint=fingerprint,
                severity=evidence["severity"],
                evidence=evidence,
            )
            session.add(report)
            session.flush()
            grouped = {}
            for finding in evidence["findings"]:
                key = (finding["type"], finding["feature"])
                grouped.setdefault(key, []).append(finding["severity"])
            for (kind, feature), severities in grouped.items():
                incident = session.scalar(
                    select(Incident).where(
                        Incident.model_version_id == version_id,
                        Incident.incident_type == kind,
                        Incident.feature == feature,
                        Incident.status != "RESOLVED",
                    )
                )
                if incident:
                    incident.latest_report_id = report.id
                    incident.occurrences += 1
                    incident.severity = str(highest([incident.severity, *severities]))
                    incident.updated_at = now()
                    action = "incident.observed"
                else:
                    incident = Incident(
                        model_version_id=version_id,
                        incident_type=kind,
                        feature=feature,
                        severity=str(highest(severities)),
                        first_report_id=report.id,
                        latest_report_id=report.id,
                    )
                    session.add(incident)
                    session.flush()
                    action = "incident.opened"
                session.add(
                    AuditEvent(
                        actor=self.actor,
                        action=action,
                        resource_type="incident",
                        resource_id=incident.id,
                        details={"report_id": report.id},
                    )
                )
            session.add(
                AuditEvent(
                    actor=self.actor,
                    action="reliability.evaluated",
                    resource_type="reliability_report",
                    resource_id=report.id,
                    details={"fingerprint": fingerprint, "severity": report.severity},
                )
            )
            return serialize(report)

    def reports(self):
        with self.factory() as session:
            return [
                serialize(row)
                for row in session.scalars(
                    select(ReliabilityReport)
                    .order_by(ReliabilityReport.created_at.desc())
                    .limit(100)
                )
            ]

    def incidents(self):
        with self.factory() as session:
            return [
                serialize(row)
                for row in session.scalars(
                    select(Incident).order_by(Incident.updated_at.desc()).limit(100)
                )
            ]

    def transition(self, incident_id, status, reason):
        if status not in {"ACKNOWLEDGED", "RESOLVED"} or not reason.strip():
            raise AegisError("Use ACKNOWLEDGED or RESOLVED and provide a nonempty reason")
        with self.factory.begin() as session:
            version_id = session.scalar(
                select(Incident.model_version_id).where(Incident.id == incident_id)
            )
            if version_id is None:
                raise AegisError("Unknown incident")
            # Same lock order as save: resolving cannot race a new observation.
            session.scalar(
                select(ModelVersion).where(ModelVersion.id == version_id).with_for_update()
            )
            incident = session.scalar(
                select(Incident).where(Incident.id == incident_id).with_for_update()
            )
            if incident is None:
                raise AegisError("Unknown incident")
            if incident.status == "RESOLVED" or incident.status == status:
                raise AegisError("Incident transition is not allowed")
            before = incident.status
            incident.status, incident.updated_at = status, now()
            session.add(
                AuditEvent(
                    actor=self.actor,
                    action="incident.transition",
                    resource_type="incident",
                    resource_id=incident.id,
                    details={"before": before, "after": status, "reason": reason},
                )
            )
            return serialize(incident)
