import time

import httpx
from sqlalchemy import func, select

from aegis.db.models import (
    AuditEvent,
    Dataset,
    DatasetVersion,
    Deployment,
    Incident,
    Investigation,
    Model,
    ModelVersion,
    ReliabilityReport,
    RetrainingRequest,
    RoutingEvent,
    TrainingRun,
    VerificationRun,
    now,
)
from aegis.deployment.config import load_policy
from aegis.registry.queries import record

TABLES = {
    "models": Model,
    "versions": ModelVersion,
    "runs": TrainingRun,
    "datasets": Dataset,
    "dataset_versions": DatasetVersion,
    "incidents": Incident,
    "investigations": Investigation,
    "reports": ReliabilityReport,
    "pipelines": RetrainingRequest,
    "deployments": Deployment,
    "audit": AuditEvent,
    "verifications": VerificationRun,
}


def snapshot(factory, settings):
    result = {"generated_at": now().isoformat(), "environment": settings.environment}
    with factory() as session:
        for name, table in TABLES.items():
            timestamp = next(
                (
                    getattr(table, c)
                    for c in ("timestamp", "updated_at", "started_at", "created_at")
                    if hasattr(table, c)
                ),
                table.id,
            )
            rows = list(session.scalars(select(table).order_by(timestamp.desc()).limit(100)))
            result[name] = [record(row) for row in rows]
            if name == "verifications":
                for row in result[name]:
                    row.pop("results", None)
        result["routing_count"] = session.scalar(select(func.count()).select_from(RoutingEvent))
    result["settings"] = {
        "backend": settings.deployment_backend,
        "mutation_enabled": bool(settings.control_token),
        "policy": load_policy(settings.rollout_policy).model_dump(),
        "airflow_configured": bool(settings.airflow_url),
        "identity": settings.actor,
        "scope": "Local development",
        "controller_enabled": settings.controller_enabled,
    }
    return result


QUERIES = {
    "requests_per_second": "sum(rate(aegis_http_requests_total[5m]))",
    "p95_seconds": "histogram_quantile(0.95, sum by (le) "
    "(rate(aegis_http_request_duration_seconds_bucket[5m])))",
    "error_ratio": 'sum(rate(aegis_http_requests_total{status=~"5.."}[5m])) / '
    "sum(rate(aegis_http_requests_total[5m]))",
}


def monitoring(settings):
    result = {"source": "Prometheus", "available": False, "series": {}}
    try:
        with httpx.Client(base_url=settings.prometheus_url, timeout=4) as client:
            end = time.time()
            for name, query in QUERIES.items():
                response = client.get(
                    "/api/v1/query_range",
                    params={"query": query, "start": end - 1800, "end": end, "step": 30},
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") != "success":
                    return result
                result["series"][name] = payload["data"]["result"]
        result["available"] = True
    except (httpx.HTTPError, ValueError, KeyError):
        result["reason"] = "Prometheus is unavailable or returned invalid data"
    return result
