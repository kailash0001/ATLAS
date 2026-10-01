import json

from sqlalchemy import select

from aegis.core.errors import AegisError
from aegis.data.fraud import canonical, digest
from aegis.db.models import (
    AuditEvent,
    DatasetVersion,
    Incident,
    Investigation,
    Model,
    ModelVersion,
    ReliabilityReport,
    TrainingRun,
)
from aegis.investigation.rules import RULES_VERSION, classify, explain
from aegis.reliability.service import serialize


def describe(finding):
    measurement = finding.get("evidence", {})
    prefix = f"{finding['type']} on {finding['feature']}"
    if finding["type"] == "PERFORMANCE_DEGRADATION":
        metric = finding["feature"]
        before = measurement.get("reference", {}).get(metric)
        after = measurement.get("current", {}).get(metric)
        return f"{prefix}: {before} -> {after}; threshold {measurement.get('threshold')}."
    return prefix + ": " + json.dumps(measurement, sort_keys=True, allow_nan=False)


def collect(session, incident, report):
    version = session.get(ModelVersion, report.model_version_id)
    model = session.get(Model, version.model_id)
    run = session.get(TrainingRun, version.training_run_id)
    dataset = session.get(DatasetVersion, run.dataset_version_id)
    evidence = report.evidence
    if incident.model_version_id != version.id:
        raise AegisError("Incident/report model lineage mismatch")
    facts = []
    for index, finding in enumerate(evidence["findings"]):
        measurement = finding.get("evidence", {})
        facts.append(
            {
                "id": f"F{index + 1}",
                "type": finding["type"],
                "feature": finding["feature"],
                "severity": finding["severity"],
                "measurement": measurement,
                "source": {"report_id": report.id, "pointer": f"/findings/{index}"},
                "summary": describe(finding),
            }
        )
    performance = evidence.get("performance", {})
    hourly = performance.get("current", {}).get("by_hour", {})
    if hourly:
        afternoon = [value for hour, value in hourly.items() if 14 <= int(hour) <= 18]
        total_error = sum(value["mae"] * value["count"] for value in hourly.values())
        interval_error = sum(value["mae"] * value["count"] for value in afternoon)
        count = sum(value["count"] for value in afternoon)
        share = interval_error / total_error if total_error > 0 else None
        facts.append(
            {
                "id": f"F{len(facts) + 1}",
                "type": "ERROR_SEGMENT",
                "feature": "hour",
                "severity": "INFO",
                "measurement": {
                    "hours_utc": [14, 18],
                    "count": count,
                    "absolute_error_share": share,
                },
                "source": {"report_id": report.id, "pointer": "/performance/current/by_hour"},
                "summary": f"Hours 14-18 UTC contain {count} outcomes; "
                f"share of total absolute forecast error: {share}.",
            }
        )
    # History includes only actual recorded observations, never synthesized deployment events.
    audit = list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource_id == incident.id, AuditEvent.timestamp <= report.created_at)
            .order_by(AuditEvent.timestamp)
            .limit(100)
        )
    )
    return {
        "incident_id": incident.id,
        "report_id": report.id,
        "report_fingerprint": report.fingerprint,
        "severity": report.severity,
        "observed_at": report.created_at.isoformat(),
        "model": {
            "name": model.name,
            "version": version.version,
            "version_id": version.id,
            "target": run.config.get("target"),
            "mlflow_run_id": run.mlflow_run_id,
            "dataset_fingerprint": dataset.fingerprint,
        },
        "facts": facts,
        "feature_drift": evidence.get("feature_drift", {}),
        "performance": performance,
        "profiles": evidence.get("profiles", {}),
        "policy": evidence.get("policy", {}),
        "policy_hash": evidence.get("policy_hash"),
        "inputs": evidence.get("inputs", {}),
        "source": evidence.get("source", {}),
        "retraining_eligible": evidence.get("retraining_allowed", False),
        "incident_history": [
            {
                "id": a.id,
                "action": a.action,
                "timestamp": a.timestamp.isoformat(),
                "details": a.details,
            }
            for a in audit
        ],
        "limitations": [
            "CPU and memory measurements unavailable for this report window",
            "HTTP latency and error-rate evidence not collected for this report window",
            "deployment timeline unavailable; registry promotion is not deployment",
            "distribution and performance changes do not establish causation",
        ],
        "runtime": {"status": "UNAVAILABLE"},
        "deployment": {"status": "UNAVAILABLE"},
    }


class InvestigationService:
    def __init__(self, factory, actor):
        self.factory, self.actor = factory, actor

    def investigate(self, incident_id):
        with self.factory.begin() as session:
            incident = session.scalar(
                select(Incident).where(Incident.id == incident_id).with_for_update()
            )
            if incident is None:
                raise AegisError("Unknown incident")
            report = session.get(ReliabilityReport, incident.latest_report_id)
            # The immutable report identifies the snapshot, independent of incident status.
            fingerprint = digest(
                canonical(
                    {"incident": incident.id, "report": report.fingerprint, "rules": RULES_VERSION}
                )
            )
            existing = session.scalar(
                select(Investigation).where(Investigation.fingerprint == fingerprint)
            )
            if existing:
                return serialize(existing)
            bundle = collect(session, incident, report)
            conclusion = classify(bundle)
            row = Investigation(
                incident_id=incident.id,
                report_id=report.id,
                fingerprint=fingerprint,
                rules_version=RULES_VERSION,
                category=conclusion["category"],
                evidence=bundle,
                conclusion=conclusion,
                explanation=explain(bundle, conclusion),
            )
            json.dumps(bundle, allow_nan=False)
            session.add(row)
            session.flush()
            session.add(
                AuditEvent(
                    actor=self.actor,
                    action="incident.investigated",
                    resource_type="investigation",
                    resource_id=row.id,
                    details={
                        "incident_id": incident.id,
                        "report_id": report.id,
                        "category": row.category,
                        "rules_version": RULES_VERSION,
                    },
                )
            )
            return serialize(row)

    def get(self, investigation_id):
        with self.factory() as session:
            row = session.get(Investigation, investigation_id)
            if row is None:
                raise AegisError("Unknown investigation")
            return serialize(row)

    def list(self):
        with self.factory() as session:
            return [
                serialize(row)
                for row in session.scalars(
                    select(Investigation).order_by(Investigation.created_at.desc()).limit(100)
                )
            ]
