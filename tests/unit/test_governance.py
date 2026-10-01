from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from aegis.core.errors import GovernanceError
from aegis.db.models import AuditEvent, Dataset, DatasetVersion, Model, ModelVersion, TrainingRun
from aegis.registry.service import GovernanceService


def seed(factory):
    with factory.begin() as session:
        model = Model(
            name="fraud-detector",
            owner="team",
            use_case="fraud",
            risk_level="high",
            environment="test",
            registry_name="fraud-detector-test",
        )
        dataset = Dataset(name="test", source="synthetic")
        session.add_all([model, dataset])
        session.flush()
        dv = DatasetVersion(dataset_id=dataset.id, fingerprint="a" * 64, manifest={})
        session.add(dv)
        session.flush()
        for version in (1, 2):
            run = TrainingRun(
                model_id=model.id,
                dataset_version_id=dv.id,
                algorithm="test",
                status="FINISHED",
                config={},
                code_revision="test",
                metrics={},
            )
            session.add(run)
            session.flush()
            session.add(
                ModelVersion(
                    model_id=model.id,
                    training_run_id=run.id,
                    version=version,
                    model_uri="test",
                    features={},
                )
            )


def test_promotion_audit_replacement_and_idempotency(database):
    seed(database)
    service = GovernanceService(database, MagicMock(), "tester")
    service.transition("fraud-detector", 1, "promote", "Reviewed validation")
    service.transition("fraud-detector", 1, "promote", "Retry")
    service.transition("fraud-detector", 2, "promote", "Better validation")
    with database() as session:
        versions = list(session.scalars(select(ModelVersion).order_by(ModelVersion.version)))
        assert [v.status for v in versions] == ["archived", "champion"]
        events = list(session.scalars(select(AuditEvent)))
        assert len(events) == 3
        assert all(e.actor == "tester" for e in events)


def test_rejected_and_champion_transitions_blocked(database):
    seed(database)
    service = GovernanceService(database, MagicMock(), "tester")
    service.transition("fraud-detector", 1, "reject", "Poor recall")
    with pytest.raises(GovernanceError):
        service.transition("fraud-detector", 1, "promote", "Try anyway")
    service.transition("fraud-detector", 2, "promote", "Reviewed")
    with pytest.raises(GovernanceError):
        service.transition("fraud-detector", 2, "archive", "Remove champion")
    with pytest.raises(GovernanceError):
        service.transition("fraud-detector", 2, "promote", " ")


def test_alias_failure_keeps_pending_and_can_retry(database):
    seed(database)
    client = MagicMock()
    client.get_registered_model.return_value.aliases = {}
    service = GovernanceService(database, client, "tester")
    service.transition("fraud-detector", 1, "promote", "Reviewed")
    client.set_registered_model_alias.side_effect = ConnectionError("Offline")
    with pytest.raises(ConnectionError):
        service.sync("fraud-detector")
    with database() as session:
        assert session.scalar(select(Model)).sync_pending
    client.set_registered_model_alias.side_effect = None
    service.sync("fraud-detector")
    with database() as session:
        assert not session.scalar(select(Model)).sync_pending
    client.set_registered_model_alias.assert_any_call("fraud-detector-test", "champion", "1")
    client.set_registered_model_alias.assert_any_call("fraud-detector-test", "candidate", "2")


def test_database_enforces_single_champion(database):
    seed(database)
    with pytest.raises(IntegrityError), database.begin() as session:
        for version in session.scalars(select(ModelVersion)):
            version.status = "champion"
