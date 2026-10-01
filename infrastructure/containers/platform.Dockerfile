FROM python:3.11.13-slim-bookworm
WORKDIR /app
COPY pyproject.toml requirements.lock alembic.ini ./
COPY aegis ./aegis
COPY apps ./apps
COPY configs ./configs
COPY tests ./tests
COPY migrations ./migrations
COPY dags ./dags
RUN pip install --no-cache-dir -c requirements.lock -e '.[dev,reliability]' \
    && useradd --create-home --uid 10002 aegis
USER aegis
ENV MLFLOW_DISABLE_AGENT_HINT=1 DO_NOT_TRACK=1 EVIDENTLY_DISABLE_TELEMETRY=1
ENTRYPOINT []
CMD ["uvicorn", "apps.control_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8100"]
