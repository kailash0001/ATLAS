FROM python:3.11.13-slim-bookworm
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -c /tmp/requirements.lock mlflow==3.16.1 "psycopg[binary]==3.2.10"
RUN useradd --create-home --uid 10001 mlflow && mkdir -p /mlflow/artifacts \
    && chown -R mlflow:mlflow /mlflow
USER mlflow
WORKDIR /mlflow
EXPOSE 5000
