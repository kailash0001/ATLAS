import httpx
from sqlalchemy import select

from aegis.core.errors import AegisError
from aegis.db.models import AuditEvent, RetrainingRequest
from aegis.remediation.service import guard


def schedule(settings, factory, request_id):
    if not settings.airflow_url or not settings.airflow_token:
        raise AegisError("Configure Airflow URL and API token to schedule this request")
    with factory.begin() as session:
        row = session.scalar(
            select(RetrainingRequest).where(RetrainingRequest.id == request_id).with_for_update()
        )
        if row is None or row.status not in {"REQUESTED", "VALIDATED", "TRAINED"}:
            raise AegisError("Request is not runnable")
        guard(session, row)
        run_id = f"aegis-{request_id}"
        response = httpx.post(
            settings.airflow_url.rstrip("/") + "/api/v2/dags/aegis_retraining/dagRuns",
            headers={"Authorization": "Bearer " + settings.airflow_token},
            timeout=10,
            json={"dag_run_id": run_id, "logical_date": None, "conf": {"request_id": request_id}},
        )
        if response.status_code == 409:
            return {"status": "already_scheduled", "dag_run_id": run_id}
        if not response.is_success:
            raise AegisError("Airflow scheduling failed; check its API configuration")
        session.add(
            AuditEvent(
                actor=settings.actor,
                action="pipeline.scheduled",
                resource_type="retraining_request",
                resource_id=row.id,
                details={"dag_run_id": run_id},
            )
        )
        return {"status": "scheduled", "dag_run_id": run_id}
