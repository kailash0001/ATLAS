FROM apache/airflow:3.1.8-python3.11
USER root
RUN mkdir -p /opt/aegis /opt/aegis-venv && chown -R airflow:root /opt/aegis /opt/aegis-venv
USER airflow
WORKDIR /opt/aegis
COPY --chown=airflow:root pyproject.toml requirements.lock alembic.ini ./
COPY --chown=airflow:root aegis ./aegis
COPY --chown=airflow:root apps ./apps
COPY --chown=airflow:root tests ./tests
COPY --chown=airflow:root configs ./configs
COPY --chown=airflow:root migrations ./migrations
COPY --chown=airflow:root dags ./dags
RUN python -m venv /opt/aegis-venv \
    && /opt/aegis-venv/bin/pip install --no-cache-dir -c requirements.lock -e '.[dev]'
ENV AIRFLOW__CORE__DAGS_FOLDER=/opt/aegis/dags \
    AIRFLOW__CORE__LOAD_EXAMPLES=false \
    AEGIS_WORKER_PYTHON=/opt/aegis-venv/bin/python \
    MLFLOW_ENABLE_TELEMETRY=false MLFLOW_DISABLE_AGENT_HINT=1
WORKDIR /opt/airflow
CMD ["standalone"]
