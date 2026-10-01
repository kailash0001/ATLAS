"""Read-only live checks: inference, durable evidence, Prometheus and Grafana."""

import json
import math
import os
from pathlib import Path

import httpx


def fetch(client, path, **kwargs):
    response = client.get(path, **kwargs)
    response.raise_for_status()
    return response.json()


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=15, trust_env=False) as api:
        readiness = fetch(api, "/health/ready")
        summary = fetch(api, "/api/v1/monitoring/summary")
        assert summary["predictions"] > 0, "Run scripts/traffic.py --labels first"
        assert summary["labeled"] > 0, "Submit actual ground-truth labels first"
        schema = fetch(api, "/openapi.json")
        assert "/api/v1/predict" in schema["paths"]
    with httpx.Client(base_url="http://127.0.0.1:9090", timeout=15, trust_env=False) as prom:
        targets = fetch(prom, "/api/v1/targets")["data"]["activeTargets"]
        assert any(t["labels"]["job"] == "aegis-inference" and t["health"] == "up" for t in targets)

        def query(expression):
            result = fetch(prom, "/api/v1/query", params={"query": expression})
            assert result["status"] == "success"
            return result["data"]["result"]

        assert float(query('aegis_serving_ready{job="aegis-inference"}')[0]["value"][1]) == 1
        for name in ("predictions", "labeled", "f1", "recall", "precision"):
            values = query(f'aegis_model_{name}{{job="aegis-inference"}}')
            assert len(values) == 1
            expected = summary[name]
            if expected is not None:
                assert math.isclose(float(values[0]["value"][1]), expected, abs_tol=1e-12)
        dashboard = json.loads(
            Path("infrastructure/grafana/dashboards/fraud-serving.json").read_text()
        )
        queries = [target["expr"] for panel in dashboard["panels"] for target in panel["targets"]]
        for expression in queries:
            query(expression.replace("$__rate_interval", "1m"))
    with httpx.Client(
        base_url="http://127.0.0.1:3000",
        timeout=15,
        trust_env=False,
        auth=(
            os.getenv("AEGIS_GRAFANA_USER", "aegis"),
            os.getenv("AEGIS_GRAFANA_PASSWORD", "aegis_local"),
        ),
    ) as grafana:
        installed = fetch(grafana, "/api/dashboards/uid/aegis-fraud-serving")
        assert len(installed["dashboard"]["panels"]) == len(dashboard["panels"])
        datasource = fetch(grafana, "/api/datasources/uid/aegis-prometheus/health")
        assert datasource["status"] == "OK", datasource
        proxied = fetch(
            grafana,
            "/api/datasources/proxy/uid/aegis-prometheus/api/v1/query",
            params={"query": 'aegis_model_predictions{job="aegis-inference"}'},
        )
        assert proxied["data"]["result"], "Grafana could not retrieve actual Prometheus data"
    print(
        json.dumps(
            {
                "readiness": readiness,
                "summary": summary,
                "prometheus_target": "up",
                "prometheus_metrics_match_database_summary": True,
                "grafana_datasource": "healthy",
                "dashboard_panels": len(dashboard["panels"]),
                "promql_queries_validated": len(queries),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
