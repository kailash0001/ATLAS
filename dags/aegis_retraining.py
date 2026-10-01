"""Airflow owns scheduling; Aegis owns durable state, gates and approval decisions."""

import os
import subprocess
from datetime import UTC, datetime, timedelta
from uuid import UUID

from airflow.sdk import dag, get_current_context, task


def run_stage(request_id, stage):
    request_id = str(UUID(str(request_id)))
    subprocess.run(
        [
            os.environ.get("AEGIS_WORKER_PYTHON", "/opt/aegis-venv/bin/python"),
            "-m",
            "aegis.cli.main",
            "remediation",
            "stage",
            request_id,
            stage,
        ],
        cwd="/opt/aegis",
        check=True,
        timeout=1800,
    )
    return request_id


@dag(
    dag_id="aegis_retraining",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=2),
    tags=["aegis", "retraining"],
)
def retraining():
    @task(retries=0, execution_timeout=timedelta(minutes=35))
    def validate_dataset():
        request_id = get_current_context()["dag_run"].conf.get("request_id")
        return run_stage(request_id, "validate")

    @task(retries=0, execution_timeout=timedelta(minutes=35))
    def train_register(request_id):
        return run_stage(request_id, "train")

    @task(retries=0, execution_timeout=timedelta(minutes=35))
    def evaluate_quality_gates(request_id):
        return run_stage(request_id, "evaluate")

    evaluate_quality_gates(train_register(validate_dataset()))


retraining()
