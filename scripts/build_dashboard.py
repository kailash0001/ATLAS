"""Generate the version-controlled Grafana dashboard from explicit PromQL queries."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = {"type": "prometheus", "uid": "aegis-prometheus"}


def build():
    panels = []

    def panel(title, expressions, unit="short", description="", kind="timeseries", height=8):
        index = len(panels)
        targets = [
            {"refId": chr(65 + i), "expr": expr, "legendFormat": legend, "datasource": SOURCE}
            for i, (legend, expr) in enumerate(expressions)
        ]
        panels.append(
            {
                "id": index + 1,
                "title": title,
                "type": kind,
                "datasource": SOURCE,
                "description": description,
                "targets": targets,
                "gridPos": {"x": (index % 2) * 12, "y": (index // 2) * 8, "w": 12, "h": height},
                "fieldConfig": {
                    "defaults": {
                        "unit": unit,
                        "custom": {"lineWidth": 2, "fillOpacity": 8, "spanNulls": False},
                    },
                    "overrides": [],
                },
                "options": {
                    "legend": {"displayMode": "table", "placement": "bottom"},
                    "tooltip": {"mode": "multi"},
                },
            }
        )

    selected = '{job="aegis-inference"}'
    predict = '{job="aegis-inference",route="/api/v1/predict"}'
    total_rate = f"sum(rate(aegis_http_requests_total{predict}[$__rate_interval]))"

    def error_rate(prefix):
        errors = predict[:-1] + f',status=~"{prefix}.."' + "}"
        rate = f"sum(rate(aegis_http_requests_total{errors}[$__rate_interval]))"
        return f"(({rate}) or (0 * {total_rate})) / {total_rate}"

    def quantile(q, metric, selector):
        return f"histogram_quantile({q}, sum by (le) (rate({metric}{selector}[$__rate_interval])))"

    panel(
        "Service health",
        [
            ("Scrape reachable", f"up{selected}"),
            ("Governed model ready", f"aegis_serving_ready{selected}"),
            ("Label metrics query available", f"aegis_business_metrics_available{selected}"),
        ],
        description="Reachability, model readiness and evidence availability are independent.",
    )
    panel(
        "Loaded version",
        [("{{model}} / v{{version}}", f"aegis_loaded_model{selected}")],
        description="Immutable loaded registry version. Restart after promotion.",
    )
    panel(
        "Inference throughput",
        [("requests/s", f"sum(rate(aegis_http_requests_total{predict}[$__rate_interval]))")],
        "reqps",
    )
    panel(
        "Inference request counts",
        [("HTTP {{status}}", f"sum by (status) (aegis_http_requests_total{predict})")],
        description="Process counters reset when the inference process restarts.",
    )
    panel(
        "End-to-end latency",
        [
            (
                f"p{int(q * 100)}",
                quantile(q, "aegis_http_request_duration_seconds_bucket", predict),
            )
            for q in (0.5, 0.95, 0.99)
        ],
        "s",
        "Includes schema validation, governance lookup, model execution and durable event write.",
    )
    panel(
        "HTTP error rate",
        [
            (
                "5xx server errors",
                error_rate("5"),
            ),
            (
                "4xx client errors",
                error_rate("4"),
            ),
        ],
        "percentunit",
        "No traffic means no error-rate evidence. "
        "Validation failures are distinct from server failures.",
    )
    panel(
        "Prediction distribution",
        [
            (
                "class {{predicted_class}}",
                f"sum by (predicted_class) "
                f"(rate(aegis_predictions_total{selected}[$__rate_interval]))",
            )
        ],
        "reqps",
    )
    panel(
        "Prediction probability distribution",
        [
            (
                "p50",
                quantile(0.5, "aegis_prediction_probability_bucket", selected),
            ),
            (
                "p95",
                quantile(0.95, "aegis_prediction_probability_bucket", selected),
            ),
        ],
        "percentunit",
    )
    panel(
        "Observed model performance",
        [
            (name, f"aegis_model_{name}{selected}")
            for name in ("precision", "recall", "f1", "false_positive_rate")
        ],
        "percentunit",
        "Computed from joined ground-truth labels in the configured rolling prediction window. "
        "Undefined denominators show no data; label selection bias can affect results.",
    )
    panel(
        "Label evidence",
        [
            ("predictions in window", f"aegis_model_predictions{selected}"),
            ("labeled predictions", f"aegis_model_labeled{selected}"),
        ],
        description="Counts come from PostgreSQL and survive process restarts. "
        "They decrease as observations leave the window.",
    )
    panel(
        "Fraud rates and label coverage",
        [
            (name, f"aegis_model_{name}{selected}")
            for name in ("predicted_fraud_rate", "observed_fraud_rate", "label_coverage")
        ],
        "percentunit",
    )
    panel(
        "Process resources",
        [("CPU cores used", f"rate(aegis_process_cpu_seconds_total{selected}[$__rate_interval])")],
        description="Process CPU seconds/second. One core at full use is 1.0; "
        "this is not host CPU percentage.",
    )
    panel("Resident memory", [("RSS", f"aegis_process_resident_memory_bytes{selected}")], "bytes")
    panel(
        "Durably recorded predictions",
        [
            (
                "{{model}} v{{version}} class {{predicted_class}}",
                f"aegis_predictions_total{selected}",
            )
        ],
        description="Incremented only after event persistence succeeds.",
    )
    dashboard = {
        "uid": "aegis-fraud-serving",
        "title": "AegisML / Fraud Serving",
        "schemaVersion": 39,
        "version": 1,
        "editable": False,
        "timezone": "browser",
        "refresh": "5s",
        "tags": ["aegisml", "phase-2"],
        "time": {"from": "now-15m", "to": "now"},
        "panels": panels,
        "annotations": {"list": []},
        "templating": {"list": []},
    }
    path = ROOT / "infrastructure/grafana/dashboards/fraud-serving.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
