from datetime import UTC, timedelta

import numpy as np
from sklearn.metrics import f1_score, recall_score
from sqlalchemy import select

from aegis.db.models import ModelVersion, RoutingEvent, TrainingRun, now
from aegis.deployment.config import RolloutPolicy


def evaluate(session, deployment):
    policy = RolloutPolicy.model_validate(deployment.policy)
    cutoff = now() - timedelta(seconds=policy.maximum_window_seconds)
    rows = list(
        session.scalars(
            select(RoutingEvent)
            .where(
                RoutingEvent.deployment_id == deployment.id,
                RoutingEvent.epoch == deployment.epoch,
                RoutingEvent.version_id == deployment.candidate_id,
                RoutingEvent.created_at >= cutoff,
            )
            .order_by(RoutingEvent.created_at.desc())
            .limit(10000)
        )
    )
    started = deployment.stage_started_at
    # SQLite returns naive UTC; PostgreSQL can return an aware session-local offset.
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    age = (now() - started).total_seconds()
    result = {
        "status": "INSUFFICIENT_DATA",
        "requests": len(rows),
        "epoch": deployment.epoch,
        "observed_seconds": round(age, 1),
        "evaluated_at": now().isoformat(),
        "failures": [],
    }
    if not rows:
        return result
    result["error_rate"] = sum(not row.success for row in rows) / len(rows)
    result["p95_ms"] = float(np.percentile([row.latency_ms for row in rows], 95))
    if len(rows) < policy.minimum_requests:
        return result
    if result["error_rate"] > policy.maximum_error_rate:
        result["failures"].append("error_rate")
    if result["p95_ms"] > policy.maximum_p95_ms:
        result["failures"].append("p95_latency")
    labeled = [row for row in rows if row.success and row.actual is not None]
    result["labels"] = len(labeled)
    if len(labeled) >= policy.minimum_labels:
        run = session.get(
            TrainingRun, session.get(ModelVersion, deployment.candidate_id).training_run_id
        )
        actual = np.array([r.actual for r in labeled])
        predicted = np.array([r.prediction for r in labeled])
        if run.config["target"] == "demand_kw":
            nonzero = np.abs(actual) > 1e-8
            if not nonzero.all():
                result["failures"].append("mape_coverage")
            else:
                result["mape_percent"] = float(np.mean(np.abs((actual - predicted) / actual)) * 100)
                if result["mape_percent"] > policy.maximum_mape_percent:
                    result["failures"].append("mape")
        else:
            predicted = predicted >= run.config["training"]["threshold"]
            result["f1"] = float(f1_score(actual, predicted, zero_division=0))
            result["recall"] = float(recall_score(actual, predicted, zero_division=0))
            if result["f1"] < policy.minimum_f1:
                result["failures"].append("f1")
            if result["recall"] < policy.minimum_recall:
                result["failures"].append("recall")
    if result["failures"]:
        result["status"] = "UNHEALTHY"
    elif age >= policy.minimum_observation_seconds and (
        not policy.require_labels or len(labeled) >= policy.minimum_labels
    ):
        result["status"] = "HEALTHY"
    return result
