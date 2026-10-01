from datetime import UTC, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aegis.core.errors import AegisError
from aegis.db.models import Deployment, ModelVersion, RetrainingRequest, RoutingEvent, now
from aegis.deployment.config import ControlSettings, RolloutPolicy
from aegis.deployment.service import DeploymentService
from aegis.registry.service import GovernanceService
from apps.control_api.main import create_app
from tests.unit import test_remediation

remediation = test_remediation.remediation


@pytest.mark.parametrize("zone", [None, UTC, timezone(timedelta(hours=5, minutes=30))])
def test_observation_age_preserves_database_timezone(zone):
    from aegis.deployment.health import evaluate

    started = now() - timedelta(seconds=60)
    started = started.astimezone(zone) if zone is not None else started.replace(tzinfo=None)
    deployment = SimpleNamespace(
        id="test",
        candidate_id="candidate",
        epoch=0,
        policy=RolloutPolicy().model_dump(),
        stage_started_at=started,
    )
    session = MagicMock()
    session.scalars.return_value = []
    assert 59 <= evaluate(session, deployment)["observed_seconds"] <= 62


@pytest.fixture
def rollout(remediation, tmp_path):
    service, args = remediation
    request = service.create(*args)
    policy_path = tmp_path / "rollout.yaml"
    policy_path.write_text("autonomy_level: 1\nminimum_observation_seconds: 1\n", encoding="utf-8")
    with service.factory.begin() as session:
        row = session.get(RetrainingRequest, request["id"])
        candidate = session.scalar(select(ModelVersion).where(ModelVersion.version == 2))
        row.candidate_version_id, row.status, row.results = (
            candidate.id,
            "APPROVED",
            {"passed": True},
        )
    settings = ControlSettings(
        **service.settings.model_dump(),
        rollout_policy=policy_path,
        control_token="test-operator-token",
        controller_enabled=False,
    )
    backends = MagicMock()
    deployment = DeploymentService(settings, service.factory, backends)
    deployment.sync = MagicMock(return_value=True)
    return deployment, request["id"]


def traffic(service, deployment_id, *, failures=0, latency=5, labeled=True, old=False):
    with service.factory.begin() as session:
        row = session.get(Deployment, deployment_id)
        row.stage_started_at = now() - timedelta(seconds=5)
        for i in range(40):
            session.add(
                RoutingEvent(
                    deployment_id=row.id,
                    version_id=row.candidate_id,
                    epoch=row.epoch,
                    success=i >= failures,
                    latency_ms=latency,
                    prediction=float(i % 2),
                    actual=float(i % 2) if labeled else None,
                    created_at=now() - timedelta(hours=1) if old else now(),
                )
            )


def test_rollout_requires_approval_and_preparation(rollout):
    service, request_id = rollout
    with service.factory.begin() as session:
        session.get(RetrainingRequest, request_id).status = "AWAITING_APPROVAL"
    with pytest.raises(AegisError, match="approval"):
        service.create(request_id, "Reviewed")
    assert not service.backends.prepare.called


def test_preparation_failure_never_routes_candidate(rollout):
    service, request_id = rollout
    service.backends.prepare.side_effect = RuntimeError("Unavailable")
    with pytest.raises(RuntimeError):
        service.create(request_id, "Reviewed")
    row = service.list()[0]
    assert row["status"] == "FAILED" and row["traffic_percent"] == 0


def test_progressive_rollout_fresh_evidence_and_rollback(rollout):
    service, request_id = rollout
    row = service.create(request_id, "Reviewed")
    assert service.create(request_id, "Retry")["id"] == row["id"]
    with pytest.raises(AegisError, match="Fresh healthy"):
        service.advance(row["id"], "Too soon")
    for expected in [25, 50, 100, 100]:
        traffic(service, row["id"])
        row = service.advance(row["id"], "Measured healthy")
        assert row["traffic_percent"] == expected
        if expected != 100:
            assert service.observe(row["id"])["health"]["status"] == "INSUFFICIENT_DATA"
    assert row["status"] == "PROMOTED"
    restored = service.rollback(row["id"], "Operator rollback")
    assert restored["status"] == "ROLLED_BACK" and restored["traffic_percent"] == 0
    with service.factory() as session:
        assert session.get(ModelVersion, row["previous_id"]).status == "champion"
        assert session.get(ModelVersion, row["candidate_id"]).status == "archived"


@pytest.mark.parametrize("case", ["errors", "latency"])
def test_automatic_health_rollback(rollout, case):
    service, request_id = rollout
    row = service.create(request_id, "Reviewed")
    traffic(
        service,
        row["id"],
        failures=10 if case == "errors" else 0,
        latency=1000 if case == "latency" else 5,
    )
    result = service.observe(row["id"])
    assert result["status"] == "ROLLED_BACK"
    assert result["health"]["status"] == "UNHEALTHY"


@pytest.mark.parametrize("case", ["missing_labels", "old_samples"])
def test_missing_or_old_evidence_blocks_progression(rollout, case):
    service, request_id = rollout
    row = service.create(request_id, "Reviewed")
    traffic(service, row["id"], labeled=case != "missing_labels", old=case == "old_samples")
    with pytest.raises(AegisError, match="Fresh healthy"):
        service.advance(row["id"], "Not enough evidence")
    assert service.list()[0]["traffic_percent"] == 10


def test_active_rollout_blocks_manual_registry_bypass(rollout):
    service, request_id = rollout
    service.create(request_id, "Reviewed")
    with pytest.raises(AegisError, match="active deployment"):
        GovernanceService(service.factory, MagicMock(), "reviewer").transition(
            "fraud-detector", 2, "promote", "Bypass traffic checks"
        )


def test_policy_levels_and_label_conflict(rollout):
    service, request_id = rollout
    with pytest.raises(AegisError, match="Autonomy"):
        service.create(request_id, "Automatic", automatic=True)
    row = service.create(request_id, "Reviewed")
    traffic(service, row["id"])
    with pytest.raises(AegisError, match="Autonomy"):
        service.advance(row["id"], "Automatic", automatic=True)
    with service.factory() as session:
        event = session.scalar(select(RoutingEvent))
        event_id, actual = event.id, event.actual
    assert service.label(event_id, actual)["actual"] == actual
    with pytest.raises(AegisError, match="Conflicting"):
        service.label(event_id, 1 - actual)


def test_control_api_readiness_authorization_and_live_state(rollout):
    service, request_id = rollout
    app = create_app(service.settings, service.factory, service)
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        snapshot = client.get("/api/v1/state").json()
        assert snapshot["models"][0]["name"] == "fraud-detector"
        assert "control_token" not in str(snapshot)
        path = f"/api/v1/pipelines/{request_id}/deploy"
        assert client.post(path, json={"reason": "Reviewed"}).status_code == 401
        response = client.post(
            path,
            json={"reason": "Reviewed"},
            headers={"Authorization": "Bearer test-operator-token"},
        )
        assert response.status_code == 200
        assert response.json()["traffic_percent"] == 10
        assert client.get("/api/v1/state").json()["deployments"][0]["id"] == response.json()["id"]


def test_bad_policy_rejected():
    with pytest.raises(ValueError):
        RolloutPolicy(autonomy_level=5)
