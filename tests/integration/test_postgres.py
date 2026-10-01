"""Optional real-PostgreSQL checks. Uses an isolated temporary database."""

import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.engine import make_url

from aegis.db.models import AuditEvent, ModelVersion, PredictionEvent
from aegis.db.session import make_engine, sessions
from aegis.investigation.service import InvestigationService
from aegis.registry.service import GovernanceService
from aegis.reliability.service import ReliabilityService
from aegis.serving.config import ServingSettings
from aegis.serving.errors import ServingError
from aegis.serving.service import InferenceService
from tests.unit.test_governance import seed


@pytest.fixture
def postgres_database(monkeypatch):
    supplied = os.environ.get("AEGIS_TEST_POSTGRES_URL")
    if not supplied:
        pytest.skip("Set AEGIS_TEST_POSTGRES_URL to enable PostgreSQL-specific tests")
    base = make_url(supplied)
    name = "aegis_test_" + uuid4().hex
    admin_url = base.set(drivername="postgresql", database="postgres")
    admin = psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True)
    admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    url = base.set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("AEGIS_DATABASE_URL", url)
    engine = make_engine(url)
    try:
        command.upgrade(Config("alembic.ini"), "head")
        yield sessions(engine)
    finally:
        engine.dispose()
        admin.execute(
            psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name))
        )
        admin.close()


@pytest.mark.integration
def test_concurrent_promotions_keep_one_champion(postgres_database):
    seed(postgres_database)
    service = GovernanceService(postgres_database, MagicMock(), "concurrent-test")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(service.transition, "fraud-detector", version, "promote", "Reviewed")
            for version in (1, 2)
        ]
        for future in futures:
            future.result(timeout=15)
    with postgres_database() as session:
        versions = list(session.scalars(select(ModelVersion)))
        assert sorted(v.status for v in versions) == ["archived", "champion"]


@pytest.mark.integration
def test_postgres_migrations_roundtrip(postgres_database):
    command.check(Config("alembic.ini"))
    command.downgrade(Config("alembic.ini"), "base")
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))


@pytest.mark.integration
def test_concurrent_deployment_creation_is_idempotent(postgres_database, config, tmp_path):
    from aegis.db.models import Deployment
    from tests.unit.test_deployment import rollout
    from tests.unit.test_remediation import remediation

    fixture = remediation.__wrapped__(postgres_database, config, tmp_path)
    service, request_id = rollout.__wrapped__(fixture, tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: service.create(request_id, "Concurrent request"), range(4))
        )
    assert len({row["id"] for row in results}) == 1
    with postgres_database() as session:
        assert len(list(session.scalars(select(Deployment)))) == 1
    assert service.backends.prepare.call_count == 2


@pytest.mark.integration
def test_concurrent_reliability_reports_are_idempotent(postgres_database):
    seed(postgres_database)
    with postgres_database() as session:
        version_id = session.scalar(select(ModelVersion)).id
    service = ReliabilityService(postgres_database, "reliability-concurrency")
    evidence = {
        "severity": "CRITICAL",
        "findings": [
            {"type": "UPSTREAM_DATA_FAILURE", "feature": "dataset", "severity": "CRITICAL"}
        ],
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(lambda _: service.save(version_id, evidence), range(4)))
    assert len({report["id"] for report in reports}) == 1
    assert len(service.reports()) == len(service.incidents()) == 1
    assert service.incidents()[0]["occurrences"] == 1
    incident_id = service.incidents()[0]["id"]
    investigator = InvestigationService(postgres_database, "investigation-concurrency")
    with ThreadPoolExecutor(max_workers=4) as pool:
        investigations = list(pool.map(lambda _: investigator.investigate(incident_id), range(4)))
    assert len({row["id"] for row in investigations}) == 1
    assert len(investigator.list()) == 1


@pytest.mark.integration
@pytest.mark.parametrize("labels", [(1, 1), (0, 1)])
def test_concurrent_labels_are_exactly_once(postgres_database, labels):
    seed(postgres_database)
    with postgres_database.begin() as session:
        version = session.scalar(select(ModelVersion))
        event = PredictionEvent(
            request_id="test",
            model_version_id=version.id,
            features={},
            probability=0.5,
            predicted_class=1,
            threshold=0.5,
            inference_ms=1,
        )
        session.add(event)
        session.flush()
        event_id = event.id
    service = InferenceService(ServingSettings(environment="test"), postgres_database)

    def label(actual):
        try:
            service.label(event_id, actual, "concurrent-label")
            return 200
        except ServingError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(label, labels))
    assert statuses == ([200, 200] if labels[0] == labels[1] else [200, 409])
    with postgres_database() as session:
        events = list(
            session.scalars(select(AuditEvent).where(AuditEvent.action == "prediction.labeled"))
        )
        assert len(events) == 1
