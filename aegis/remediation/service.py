from datetime import UTC

from sqlalchemy import select

from aegis.core.config import ModelConfig
from aegis.core.errors import AegisError
from aegis.data.fraud import canonical, digest, load_dataset
from aegis.db.models import (
    AuditEvent,
    Incident,
    Investigation,
    Model,
    ModelVersion,
    ReliabilityReport,
    RetrainingRequest,
    VerificationRun,
    now,
)
from aegis.reliability.analysis import analyze
from aegis.reliability.policy import Policy
from aegis.reliability.service import serialize
from aegis.reliability.workload import context
from aegis.remediation.gates import evaluate_candidate
from aegis.remediation.policy import GatePolicy
from aegis.remediation.verification import source_hash
from aegis.training.pipeline import validate_features
from aegis.training.service import TrainingService


def fresh(timestamp, hours):
    return (
        0
        <= (now() - timestamp.replace(tzinfo=timestamp.tzinfo or UTC)).total_seconds()
        <= hours * 3600
    )


def audit(session, actor, request, action, **details):
    session.add(
        AuditEvent(
            actor=actor,
            action=f"retraining.{action}",
            resource_type="retraining_request",
            resource_id=request.id,
            details=details,
        )
    )


def current_baseline(session, request):
    baseline = session.get(ModelVersion, request.baseline_version_id)
    if baseline.status not in {"candidate", "champion"}:
        candidate = (
            session.get(ModelVersion, request.candidate_version_id)
            if request.candidate_version_id
            else None
        )
        if candidate is None or candidate.status != "champion":
            raise AegisError(
                "Baseline was retired; create a new request against an eligible baseline"
            )
    champion = session.scalar(
        select(ModelVersion).where(
            ModelVersion.model_id == request.model_id, ModelVersion.status == "champion"
        )
    )
    if champion is not None and champion.id not in {
        request.baseline_version_id,
        request.candidate_version_id,
    }:
        raise AegisError("Champion changed; create a new request against the current baseline")


def guard(session, request):
    policy = GatePolicy.model_validate(request.policy)
    if request.source_hash != source_hash():
        raise AegisError("Source changed; verification and request must be regenerated")
    verification = session.get(VerificationRun, request.verification_id)
    if (
        not verification.passed
        or verification.source_hash != request.source_hash
        or not fresh(verification.created_at, policy.maximum_verification_age_hours)
    ):
        raise AegisError("Passing, current, source-matched verification is required")
    current_baseline(session, request)
    if request.investigation_id:
        investigation = session.get(Investigation, request.investigation_id)
        incident = session.get(Incident, investigation.incident_id)
        report = session.get(ReliabilityReport, investigation.report_id)
        if (
            not investigation.conclusion.get("retraining_eligible")
            or investigation.category not in {"DATA", "MODEL"}
            or not report.evidence.get("retraining_allowed")
            or incident.status == "RESOLVED"
            or incident.latest_report_id != report.id
            or report.model_version_id != request.baseline_version_id
            or not fresh(report.created_at, policy.maximum_evidence_age_hours)
        ):
            raise AegisError("Investigation is blocked, superseded, resolved, stale or mismatched")


def deployment_eligible(session, request):
    guard(session, request)
    policy = GatePolicy.model_validate(request.policy)
    if request.status != "APPROVED" or not request.results.get("passed"):
        raise AegisError("Candidate requires passed quality gates and explicit approval")
    if not fresh(request.updated_at, policy.maximum_approval_age_hours):
        raise AegisError("Approval expired; obtain fresh evaluation and approval")
    candidate = session.get(ModelVersion, request.candidate_version_id)
    if candidate is None or candidate.status not in {"candidate", "champion"}:
        raise AegisError("Candidate is no longer eligible")
    if session.get(Model, request.model_id).sync_pending:
        raise AegisError("Registry synchronization must complete before eligibility")


class RemediationService:
    def __init__(self, settings, factory):
        self.settings, self.factory = settings, factory

    def get(self, request_id):
        with self.factory() as session:
            row = session.get(RetrainingRequest, request_id)
            if row is None:
                raise AegisError("Unknown retraining request")
            return serialize(row)

    def list(self):
        with self.factory() as session:
            return [
                serialize(row)
                for row in session.scalars(
                    select(RetrainingRequest)
                    .order_by(RetrainingRequest.created_at.desc())
                    .limit(100)
                )
            ]

    def create(
        self,
        name,
        baseline,
        dataset_path,
        algorithm,
        policy,
        quality,
        verification_id,
        reason,
        investigation_id=None,
    ):
        if not reason.strip():
            raise AegisError("A nonempty request reason is required")
        config, _, info = context(self.settings, self.factory, name, baseline)
        manifest, _ = load_dataset(dataset_path)
        if manifest["generator"]["name"] != config.dataset.name:
            raise AegisError("Dataset workload does not match baseline")
        expected = (
            self.settings.data_root / config.dataset.name / manifest["fingerprint"]
        ).resolve()
        if dataset_path.resolve() != expected:
            raise AegisError("Use the canonical versioned dataset under AEGIS_DATA_ROOT")
        config.dataset = type(config.dataset).model_validate(manifest["generator"])
        if algorithm not in config.training.algorithms:
            raise AegisError("Algorithm must be configured on the baseline workload")
        if set(quality.ranges) != set(config.features.numeric) or set(quality.categories) != set(
            config.features.categorical
        ):
            raise AegisError("Quality policy must cover every model feature")
        frozen = {
            "baseline": info["model_version_id"],
            "dataset": manifest["fingerprint"],
            "algorithm": algorithm,
            "config": config.model_dump(),
            "policy": policy.model_dump(),
            "quality": quality.model_dump(),
            "source": source_hash(),
            "investigation": investigation_id,
            "verification": verification_id,
        }
        fingerprint = digest(canonical(frozen))
        with self.factory.begin() as session:
            version = session.get(ModelVersion, info["model_version_id"])
            session.scalar(select(Model).where(Model.id == version.model_id).with_for_update())
            existing = session.scalar(
                select(RetrainingRequest).where(RetrainingRequest.fingerprint == fingerprint)
            )
            if existing:
                return serialize(existing)
            if session.get(VerificationRun, verification_id) is None:
                raise AegisError("Unknown test verification")
            if investigation_id and session.get(Investigation, investigation_id) is None:
                raise AegisError("Unknown investigation")
            row = RetrainingRequest(
                model_id=version.model_id,
                baseline_version_id=version.id,
                verification_id=verification_id,
                investigation_id=investigation_id,
                fingerprint=fingerprint,
                requested_by=self.settings.actor,
                reason=reason,
                dataset_path=f"{config.dataset.name}/{manifest['fingerprint']}",
                dataset_fingerprint=manifest["fingerprint"],
                source_hash=frozen["source"],
                algorithm=algorithm,
                config=config.model_dump(),
                policy=policy.model_dump(mode="json"),
                quality_policy=quality.model_dump(mode="json"),
            )
            guard(session, row)
            session.add(row)
            session.flush()
            audit(
                session,
                self.settings.actor,
                row,
                "requested",
                trigger="investigation" if investigation_id else "manual",
            )
            return serialize(row)

    def stage(self, request_id, stage):
        transitions = {
            "validate": ("REQUESTED", "VALIDATING", "VALIDATED"),
            "train": ("VALIDATED", "TRAINING", "TRAINED"),
            "evaluate": ("TRAINED", "EVALUATING", "AWAITING_APPROVAL"),
        }
        if stage not in transitions:
            raise AegisError("Unknown workflow stage")
        expected, running, finished = transitions[stage]
        done = {
            "validate": {
                "VALIDATED",
                "TRAINING",
                "TRAINED",
                "EVALUATING",
                "AWAITING_APPROVAL",
                "APPROVED",
                "REJECTED",
            },
            "train": {"TRAINED", "EVALUATING", "AWAITING_APPROVAL", "APPROVED", "REJECTED"},
            "evaluate": {"AWAITING_APPROVAL", "APPROVED", "REJECTED"},
        }
        with self.factory.begin() as session:
            row = session.scalar(
                select(RetrainingRequest)
                .where(RetrainingRequest.id == request_id)
                .with_for_update()
            )
            if row is None:
                raise AegisError("Unknown retraining request")
            if row.status in done[stage]:
                return serialize(row)
            if row.status != expected:
                raise AegisError(f"Stage {stage} requires {expected}; request is {row.status}")
            guard(session, row)
            row.status, row.updated_at = running, now()
            audit(session, self.settings.actor, row, f"{stage}.started")
            snapshot = serialize(row)
        try:
            config = ModelConfig.model_validate(snapshot["config"])
            policy = GatePolicy.model_validate(snapshot["policy"])
            quality = Policy.model_validate(snapshot["quality_policy"])
            manifest, frames = load_dataset(self.settings.data_root / snapshot["dataset_path"])
            if manifest["fingerprint"] != snapshot["dataset_fingerprint"]:
                raise AegisError("Dataset changed after request creation")
            # Revalidate each boundary, including immediately before training and evaluation.
            for frame in frames.values():
                validate_features(frame, config)
                evidence = analyze(frames["train"], frame, config, quality)
                if evidence["recommendation"] == "INVESTIGATE_UPSTREAM":
                    raise AegisError(
                        "Dataset failed quality rules; investigate upstream before retraining"
                    )
            results = dict(snapshot["results"])
            candidate_id = snapshot["candidate_version_id"]
            if stage == "validate":
                results["validation"] = {
                    "passed": True,
                    "dataset": manifest["fingerprint"],
                    "rows": {k: len(v) for k, v in frames.items()},
                }
            elif stage == "train":
                trained = TrainingService(self.settings, self.factory).train(
                    config,
                    self.settings.data_root / snapshot["dataset_path"],
                    snapshot["algorithm"],
                    request_id=request_id,
                )
                with self.factory() as session:
                    candidate_id = session.scalar(
                        select(ModelVersion.id).where(
                            ModelVersion.training_run_id == trained["run_id"]
                        )
                    )
                results["training"] = trained
            else:
                with self.factory() as session:
                    baseline = session.get(ModelVersion, snapshot["baseline_version_id"])
                    candidate = session.get(ModelVersion, candidate_id)
                    model = session.get(Model, snapshot["model_id"])
                    baseline_number, candidate_number, name = (
                        baseline.version,
                        candidate.version,
                        model.name,
                    )
                _, _, baseline_info = context(self.settings, self.factory, name, baseline_number)
                _, _, candidate_info = context(self.settings, self.factory, name, candidate_number)
                measured = evaluate_candidate(
                    self.settings,
                    config,
                    policy,
                    quality,
                    frames["validation"],
                    candidate_info,
                    baseline_info,
                )
                results.update(measured)
                results["gates"].extend(
                    [
                        {
                            "name": "dataset_quality",
                            "passed": True,
                            "evidence": results["validation"],
                        },
                        {
                            "name": "source_matched_tests",
                            "passed": True,
                            "evidence": {"verification_id": snapshot["verification_id"]},
                        },
                    ]
                )
                if not results["passed"]:
                    finished = "REJECTED"
            with self.factory.begin() as session:
                row = session.scalar(
                    select(RetrainingRequest)
                    .where(RetrainingRequest.id == request_id)
                    .with_for_update()
                )
                guard(session, row)
                if row.status != running:
                    raise AegisError("Workflow ownership changed")
                row.status, row.results, row.candidate_version_id = finished, results, candidate_id
                row.updated_at = now()
                audit(session, self.settings.actor, row, f"{stage}.completed", status=finished)
                return serialize(row)
        except Exception as exc:
            with self.factory.begin() as session:
                row = session.scalar(
                    select(RetrainingRequest)
                    .where(RetrainingRequest.id == request_id)
                    .with_for_update()
                )
                if row.status == running:
                    row.status, row.error, row.updated_at = "FAILED", type(exc).__name__, now()
                    row.results = {
                        **row.results,
                        "failure": {
                            "stage": stage,
                            "reason": str(exc)
                            if isinstance(exc, AegisError)
                            else type(exc).__name__,
                        },
                    }
                    audit(session, self.settings.actor, row, "failed", stage=stage, error=row.error)
            raise

    def decide(self, request_id, approve, reason):
        if not reason.strip():
            raise AegisError("A review reason is required")
        with self.factory.begin() as session:
            model_id = session.scalar(
                select(RetrainingRequest.model_id).where(RetrainingRequest.id == request_id)
            )
            session.scalar(select(Model).where(Model.id == model_id).with_for_update())
            row = session.scalar(
                select(RetrainingRequest)
                .where(RetrainingRequest.id == request_id)
                .with_for_update()
            )
            if row is None or row.status != "AWAITING_APPROVAL":
                raise AegisError("Only a candidate awaiting approval can be reviewed")
            guard(session, row)
            row.status = "APPROVED" if approve else "REJECTED"
            row.updated_at = now()
            if approve:
                deployment_eligible(session, row)
            audit(
                session,
                self.settings.actor,
                row,
                "approved" if approve else "rejected",
                reason=reason,
            )
            return serialize(row)

    def eligible(self, request_id):
        with self.factory() as session:
            row = session.get(RetrainingRequest, request_id)
            if row is None:
                raise AegisError("Unknown retraining request")
            deployment_eligible(session, row)
            return {
                "request_id": row.id,
                "candidate_version_id": row.candidate_version_id,
                "eligible_for_canary": True,
                "deployed": False,
            }
