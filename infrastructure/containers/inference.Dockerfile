FROM python:3.11.13-slim-bookworm
WORKDIR /app
COPY requirements.lock pyproject.toml ./
COPY aegis ./aegis
COPY apps ./apps
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --no-cache-dir -c requirements.lock . \
    && useradd --create-home --uid 10002 aegis
USER aegis
ENV MLFLOW_ENABLE_TELEMETRY=false MLFLOW_DISABLE_AGENT_HINT=1
EXPOSE 8000
CMD ["uvicorn", "apps.inference.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--timeout-keep-alive", "5", "--limit-concurrency", "64"]
