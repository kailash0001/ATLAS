from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from aegis.core.config import Settings
from aegis.core.errors import AegisError
from aegis.data.fraud import load_dataset, setup_dataset
from aegis.db.models import (
    DatasetVersion,
    Incident,
    Investigation,
    Model,
    ModelVersion,
    ReliabilityReport,
    RetrainingAttempt,
    RetrainingRequest,
    TrainingRun,
    VerificationRun,
    now,
)
from aegis.registry.service import GovernanceService
from aegis.reliability.policy import load_policy
from aegis.remediation.policy import GatePolicy
from aegis.remediation.service import RemediationService
from aegis.remediation.verification import source_hash
from tests.unit.test_governance import seed


@pytest.fixture
def remediation(database, config, tmp_path):
    seed(database)
    settings = Settings(data_root=tmp_path / "data", environment="test", actor="requester")
    path = setup_dataset(config.dataset, settings.data_root)
    manifest, _ = load_dataset(path)
    with database.begin() as session:
        dataset = session.scalar(select(DatasetVersion))
        dataset.fingerprint, dataset.manifest = manifest["fingerprint"], manifest
        session.scalar(select(Model)).sync_pending = False
        for run in session.scalars(select(TrainingRun)):
            run.config = config.model_dump()
        for version in session.scalars(select(ModelVersion)):
            version.features = config.features.model_dump()
        verification = VerificationRun(
            source_hash=source_hash(),
            passed=True,
            results={"fixture": "trusted test attestation; production verifier runs real tests"},
        )
        session.add(verification)
        session.flush()
        verification_id = verification.id
    service = RemediationService(settings, database)
    args = (
        config.name,
        1,
        path,
        "random_forest",
        GatePolicy(),
        load_policy(Path("configs/reliability/fraud.yaml")),
        verification_id,
        "Reviewed request",
    )
    return service, args


def test_request_and_validation_idempotent(remediation):
    service, args = remediation
    row = service.create(*args)
    assert service.create(*args)["id"] == row["id"]
    assert service.stage(row["id"], "validate")["status"] == "VALIDATED"
    assert service.stage(row["id"], "validate")["status"] == "VALIDATED"
    assert len(service.list()) == 1
    with pytest.raises(AegisError, match="approval"):
        service.eligible(row["id"])


@pytest.mark.parametrize("case", ["failed", "stale", "source"])
def test_test_attestation_is_required(remediation, case):
    service, args = remediation
    with service.factory.begin() as session:
        verification = session.get(VerificationRun, args[6])
        if case == "failed":
            verification.passed = False
        elif case == "stale":
            verification.created_at = now() - timedelta(days=2)
        else:
            verification.source_hash = "0" * 64
    with pytest.raises(AegisError, match="verification"):
        service.create(*args)


def test_tampered_dataset_fails_closed(remediation):
    service, args = remediation
    request = service.create(*args)
    (args[2] / "train.csv").write_text("tampered", encoding="utf-8")
    with pytest.raises(AegisError):
        service.stage(request["id"], "validate")
    row = service.get(request["id"])
    assert row["status"] == "FAILED"
    assert row["results"]["failure"]["stage"] == "validate"


def test_running_stage_is_never_retrained(remediation):
    service, args = remediation
    request = service.create(*args)
    with service.factory.begin() as session:
        session.get(RetrainingRequest, request["id"]).status = "TRAINING"
    with pytest.raises(AegisError, match="TRAINING"):
        service.stage(request["id"], "train")
    assert service.get(request["id"])["status"] == "TRAINING"


def test_orphaned_managed_candidate_cannot_bypass_approval(remediation):
    service, args = remediation
    request = service.create(*args)
    with service.factory.begin() as session:
        candidate = session.scalar(select(ModelVersion).where(ModelVersion.version == 2))
        row = session.get(RetrainingRequest, request["id"])
        row.status = "FAILED"
        session.add(RetrainingAttempt(request_id=row.id, training_run_id=candidate.training_run_id))
    governance = GovernanceService(service.factory, MagicMock(), "reviewer")
    with pytest.raises(AegisError, match="approval"):
        governance.transition(args[0], 2, "promote", "Orphan candidate")


def test_retired_baseline_blocks_training(remediation):
    service, args = remediation
    request = service.create(*args)
    with service.factory.begin() as session:
        session.scalar(select(ModelVersion).where(ModelVersion.version == 1)).status = "rejected"
    with pytest.raises(AegisError, match="retired"):
        service.stage(request["id"], "validate")


def test_expired_approval_blocks_eligibility(remediation):
    service, args = remediation
    request = service.create(*args)
    with service.factory.begin() as session:
        row = session.get(RetrainingRequest, request["id"])
        row.status, row.results = "APPROVED", {"passed": True}
        row.updated_at = now() - timedelta(days=2)
    with pytest.raises(AegisError, match="Approval expired"):
        service.eligible(request["id"])


def test_approval_and_promotion_cannot_bypass_gates(remediation):
    service, args = remediation
    request = service.create(*args)
    with service.factory.begin() as session:
        candidate = session.scalar(select(ModelVersion).where(ModelVersion.version == 2))
        row = session.get(RetrainingRequest, request["id"])
        row.candidate_version_id = candidate.id
        row.status = "AWAITING_APPROVAL"
        row.results = {"passed": True}
        session.add(RetrainingAttempt(request_id=row.id, training_run_id=candidate.training_run_id))
    governance = GovernanceService(service.factory, MagicMock(), "reviewer")
    with pytest.raises(AegisError, match="approval"):
        governance.transition(args[0], 2, "promote", "Try to bypass")
    assert service.decide(request["id"], True, "Reviewed quality evidence")["status"] == "APPROVED"
    assert service.eligible(request["id"])["eligible_for_canary"]
    governance.transition(args[0], 2, "promote", "Reviewed")


def test_gate_rejection_and_changed_champion_block_approval(remediation):
    service, args = remediation
    request = service.create(*args)
    with service.factory.begin() as session:
        row = session.get(RetrainingRequest, request["id"])
        row.status, row.results = "AWAITING_APPROVAL", {"passed": False}
    with pytest.raises(AegisError):
        service.decide(request["id"], True, "Cannot override")
    with service.factory.begin() as session:
        session.scalar(select(ModelVersion).where(ModelVersion.version == 2)).status = "champion"
    with pytest.raises(AegisError, match="Champion changed"):
        service.decide(request["id"], True, "Old baseline")


@pytest.mark.parametrize("blocked", [True, False])
def test_investigation_trigger_rechecks_quality_and_freshness(remediation, blocked):
    service, args = remediation
    with service.factory.begin() as session:
        baseline = session.scalar(select(ModelVersion).where(ModelVersion.version == 1))
        report = ReliabilityReport(
            model_version_id=baseline.id,
            fingerprint="b" * 64,
            severity="HIGH",
            evidence={"retraining_allowed": not blocked},
        )
        session.add(report)
        session.flush()
        incident = Incident(
            model_version_id=baseline.id,
            incident_type="DATA_DRIFT",
            feature="amount",
            severity="HIGH",
            first_report_id=report.id,
            latest_report_id=report.id,
        )
        session.add(incident)
        session.flush()
        investigation = Investigation(
            incident_id=incident.id,
            report_id=report.id,
            fingerprint="c" * 64,
            rules_version="1",
            category="DATA",
            evidence={},
            conclusion={"retraining_eligible": True},
            explanation="test",
        )
        session.add(investigation)
        session.flush()
        investigation_id, report_id = investigation.id, report.id
    if blocked:
        with pytest.raises(AegisError, match="Investigation"):
            service.create(*args, investigation_id=investigation_id)
    else:
        row = service.create(*args, investigation_id=investigation_id)
        with service.factory.begin() as session:
            session.get(ReliabilityReport, report_id).created_at = now() - timedelta(days=2)
        with pytest.raises(AegisError, match="stale"):
            service.stage(row["id"], "validate")
