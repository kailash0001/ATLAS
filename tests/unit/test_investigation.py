import copy
import json

import httpx
import pytest
from sqlalchemy import select

from aegis.core.errors import AegisError
from aegis.db.models import AuditEvent, ModelVersion
from aegis.investigation.local_ai import arrange, save_explanation
from aegis.investigation.rules import classify
from aegis.investigation.service import InvestigationService
from aegis.reliability.service import ReliabilityService
from tests.unit.test_governance import seed


def evidence(kind="DATA_DRIFT", allowed=True):
    return {
        "severity": "HIGH",
        "retraining_allowed": allowed,
        "findings": [
            {
                "type": kind,
                "severity": "HIGH",
                "feature": "occupancy",
                "evidence": {"distance": 0.4, "threshold": 0.15},
            }
        ],
        "performance": {"current": {"status": "evaluated"}},
    }


@pytest.fixture
def investigated(database):
    seed(database)
    with database() as session:
        version = session.scalar(select(ModelVersion)).id
    reliability = ReliabilityService(database, "tester")
    reliability.save(version, evidence())
    incident = reliability.incidents()[0]
    service = InvestigationService(database, "tester")
    return service, service.investigate(incident["id"]), reliability, version


def test_persistent_citations_idempotency_and_new_evidence(investigated, database):
    service, row, reliability, version = investigated
    assert row["category"] == "DATA"
    assert row["conclusion"]["automatic_action"] == "NONE"
    assert row["evidence"]["runtime"]["status"] == "UNAVAILABLE"
    assert row["evidence"]["facts"][0]["source"]["report_id"] == row["report_id"]
    assert service.investigate(row["incident_id"])["id"] == row["id"]
    assert service.get(row["id"])["fingerprint"] == row["fingerprint"]
    reliability.save(version, {**evidence(), "batch": "new"})
    newer = service.investigate(row["incident_id"])
    assert newer["id"] != row["id"]
    assert len(service.list()) == 2
    with database() as session:
        audits = list(
            session.scalars(select(AuditEvent).where(AuditEvent.action == "incident.investigated"))
        )
        assert len(audits) == 2
    with pytest.raises(AegisError):
        service.investigate("unknown")


@pytest.mark.parametrize(
    "kind,category",
    [
        ("SCHEMA_CHANGE", "UPSTREAM_SYSTEM"),
        ("OUT_OF_RANGE_FEATURE", "UPSTREAM_SYSTEM"),
        ("PERFORMANCE_DEGRADATION", "MODEL"),
        ("DATA_DRIFT", "DATA"),
        ("RESOURCE_EXHAUSTION", "INFRASTRUCTURE"),
        ("LATENCY_DEGRADATION", "INFRASTRUCTURE"),
        ("DEPLOYMENT_REGRESSION", "DEPLOYMENT"),
        ("PREDICTION_DRIFT", "UNKNOWN"),
        ("MISSING_DATA", "UNKNOWN"),
    ],
)
def test_categories_are_rules_not_ai(investigated, kind, category):
    _, row, _, _ = investigated
    bundle = copy.deepcopy(row["evidence"])
    bundle["facts"][0]["type"] = kind
    result = classify(bundle)
    assert result["category"] == category
    if category not in {"DATA", "MODEL"}:
        assert not result["retraining_eligible"]
        assert "consider_retraining" not in result["steps"]


def test_source_failure_wins_over_performance(investigated):
    _, row, _, _ = investigated
    bundle = copy.deepcopy(row["evidence"])
    bundle["facts"].extend(
        [
            {"id": "F2", "type": "UPSTREAM_DATA_FAILURE", "measurement": {}},
            {"id": "F3", "type": "PERFORMANCE_DEGRADATION", "measurement": {}},
        ]
    )
    result = classify(bundle)
    assert result["category"] == "UPSTREAM_SYSTEM"
    assert not result["retraining_eligible"]


def transport_for(selection):
    def handler(request):
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "local-test:latest"}]})
        body = json.loads(request.content)
        assert not body["stream"] and body["format"]["additionalProperties"] is False
        return httpx.Response(200, json={"message": {"content": json.dumps(selection)}})

    return httpx.MockTransport(handler)


def test_local_ai_grounded_and_audited(investigated):
    service, row, _, _ = investigated
    result = save_explanation(
        service,
        row["id"],
        "local-test",
        transport=transport_for({"fact_ids": ["F1"], "step_ids": ["review_drift"]}),
    )
    assert result["status"] == "ACCEPTED"
    assert "0.4" in result["result"]["explanation"]
    assert service.get(row["id"])["conclusion"] == row["conclusion"]


@pytest.mark.parametrize(
    "selection",
    [
        {"fact_ids": ["FAKE"], "step_ids": ["review_drift"]},
        {"fact_ids": [], "step_ids": ["review_drift"]},
        {"fact_ids": ["F1"], "step_ids": ["deploy_now"]},
        {"fact_ids": ["F1"], "step_ids": ["review_drift"], "explanation": "CPU 99%"},
    ],
)
def test_local_ai_cannot_invent_metrics_or_actions(investigated, selection):
    _, row, _, _ = investigated
    status, result = arrange(row, "local-test", transport=transport_for(selection))
    assert status == "REJECTED"
    assert "explanation" not in result


def test_local_ai_offline_and_cloud_rejected(investigated):
    _, row, _, _ = investigated

    def offline(request):
        raise httpx.ConnectError("offline")

    assert arrange(row, "local-test", transport=httpx.MockTransport(offline))[0] == "UNAVAILABLE"
    with pytest.raises(AegisError):
        arrange(row, "model-cloud")
    malformed_inventory = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    assert arrange(row, "local-test", transport=malformed_inventory)[0] == "REJECTED"
