from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from aegis.core.config import load_config
from aegis.core.errors import AegisError
from aegis.data.fraud import load_dataset, setup_dataset
from aegis.data.maintenance import generate, inject
from aegis.db.models import AuditEvent, Incident, ModelVersion
from aegis.reliability.analysis import analyze
from aegis.reliability.policy import load_policy
from aegis.reliability.service import ReliabilityService
from tests.unit.test_governance import seed


@pytest.fixture
def maintenance():
    config = load_config(Path("configs/models/maintenance.yaml"))
    config.dataset.samples = 1000
    return config, load_policy(Path("configs/reliability/maintenance.yaml"))


def test_maintenance_reproducible_disjoint(maintenance, tmp_path):
    config, _ = maintenance
    path = setup_dataset(config.dataset, tmp_path)
    assert setup_dataset(config.dataset, tmp_path) == path
    _, frames = load_dataset(path)
    assert sum(len(frame) for frame in frames.values()) == 1000
    assert not set(frames["train"].reading_id) & set(frames["test"].reading_id)


def test_healthy_and_missing_labels_are_distinct(maintenance):
    config, policy = maintenance
    frame = generate(config.dataset)
    report = analyze(frame, frame.copy(), config, policy)
    assert report["severity"] == "INFO"
    assert not report["retraining_allowed"]
    frame["prediction_probability"] = np.where(frame.failure == 1, 0.8, 0.2)
    report = analyze(frame, frame.copy(), config, policy)
    assert report["severity"] == "HEALTHY"
    assert report["performance"]["current"]["f1"] == 1


@pytest.mark.parametrize(
    "scenario,kind",
    [
        ("sensor-corruption", "OUT_OF_RANGE_FEATURE"),
        ("schema", "SCHEMA_CHANGE"),
        ("new-category", "SCHEMA_CHANGE"),
    ],
)
def test_faults_block_retraining(maintenance, scenario, kind):
    config, policy = maintenance
    reference = generate(config.dataset)
    current = inject(reference, scenario)
    report = analyze(reference, current, config, policy)
    assert report["severity"] == "CRITICAL"
    assert not report["retraining_allowed"]
    assert report["recommendation"] == "INVESTIGATE_UPSTREAM"
    assert kind in {f["type"] for f in report["findings"]}
    pd.testing.assert_frame_equal(reference, generate(config.dataset))


def test_drift_prediction_and_performance_evidence(maintenance):
    config, policy = maintenance
    reference = generate(config.dataset)
    reference["prediction_probability"] = np.where(reference.failure == 1, 0.8, 0.2)
    current = inject(reference, "drift")
    current["prediction_probability"] = 1 - reference.prediction_probability
    report = analyze(reference, current, config, policy)
    kinds = {f["type"] for f in report["findings"]}
    assert {"DATA_DRIFT", "PREDICTION_DRIFT", "PERFORMANCE_DEGRADATION"} <= kinds
    assert report["retraining_allowed"]
    assert report["recommendation"] == "REVIEW_MODEL"


@pytest.mark.parametrize("bad", [np.inf, "broken"])
def test_invalid_numeric_is_quality_failure(maintenance, bad):
    config, policy = maintenance
    reference = generate(config.dataset)
    current = reference.copy()
    current["temperature"] = current.temperature.astype(object)
    current.loc[0, "temperature"] = bad
    report = analyze(reference, current, config, policy)
    assert report["severity"] == "CRITICAL"
    assert not report["retraining_allowed"]


def test_empty_data_and_sparse_labels_never_healthy(maintenance):
    config, policy = maintenance
    reference = generate(config.dataset)
    report = analyze(reference, reference.iloc[:0], config, policy)
    assert report["severity"] == "WARNING"
    assert report["performance"]["current"]["status"] == "unavailable"
    empty_window = pd.DataFrame(
        columns=[*config.features.all, config.target, "prediction_probability"]
    )
    empty_report = analyze(reference, empty_window, config, policy)
    assert empty_report["severity"] == "WARNING"
    assert {f["type"] for f in empty_report["findings"]} == {"MISSING_DATA"}
    reference["prediction_probability"] = 0.5
    reference.loc[reference.index[20:], "failure"] = np.nan
    report = analyze(reference, reference, config, policy)
    assert report["performance"]["current"]["status"] == "insufficient"
    assert not report["retraining_allowed"]


def test_invalid_labels_block_model_recommendations(maintenance):
    config, policy = maintenance
    frame = generate(config.dataset)
    frame["prediction_probability"] = 0.5
    current = frame.copy()
    current.loc[0, "failure"] = 5
    report = analyze(frame, current, config, policy)
    assert report["recommendation"] == "INVESTIGATE_UPSTREAM"
    assert not report["retraining_allowed"]


def test_incident_dedup_audit_and_lifecycle(maintenance, database):
    config, policy = maintenance
    seed(database)
    with database() as session:
        version = session.scalar(select(ModelVersion)).id
    reference = generate(config.dataset)
    report = analyze(reference, inject(reference, "sensor-corruption"), config, policy)
    service = ReliabilityService(database, "tester")
    first = service.save(version, report)
    assert service.save(version, report)["id"] == first["id"]
    incident = service.incidents()[0]
    assert incident["occurrences"] == 1
    service.transition(incident["id"], "ACKNOWLEDGED", "Inspecting sensor")
    second_evidence = {**report, "source": {"batch": "second"}}
    service.save(version, second_evidence)
    with database() as session:
        updated = session.get(Incident, incident["id"])
        assert updated.occurrences == 2
        assert updated.status == "ACKNOWLEDGED"
    service.transition(incident["id"], "RESOLVED", "Replaced sensor and reviewed evidence")
    with pytest.raises(AegisError):
        service.transition(incident["id"], "ACKNOWLEDGED", "Retry")
    service.save(version, {**report, "source": {"batch": "third"}})
    matching = [
        i
        for i in service.incidents()
        if i["feature"] == incident["feature"] and i["incident_type"] == incident["incident_type"]
    ]
    assert {i["status"] for i in matching} == {"OPEN", "RESOLVED"}
    with database() as session:
        audits = list(session.scalars(select(AuditEvent)))
        assert all(event.actor == "tester" for event in audits)
        assert any(event.action == "incident.transition" for event in audits)


def test_policy_validation(maintenance):
    _, policy = maintenance
    with pytest.raises(ValueError):
        type(policy)(ranges={"temperature": (20, 0)})
    with pytest.raises(ValueError):
        type(policy)(critical_drift_distance=0.1)
    assert load_policy(Path("configs/reliability/fraud.yaml")).categories["card_present"] == [
        "yes",
        "no",
    ]
