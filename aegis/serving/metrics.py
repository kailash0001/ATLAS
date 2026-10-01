import math

import psutil
from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from aegis.serving.service import InferenceService


class RuntimeCollector:
    def __init__(self, service: InferenceService):
        self.service = service
        self.process = psutil.Process()

    def collect(self):
        cpu = self.process.cpu_times()
        yield CounterMetricFamily(
            "aegis_process_cpu_seconds", "Process CPU time", value=cpu.user + cpu.system
        )
        yield GaugeMetricFamily(
            "aegis_process_resident_memory_bytes",
            "Resident memory",
            value=self.process.memory_info().rss,
        )
        yield GaugeMetricFamily(
            "aegis_process_start_time_seconds",
            "Process start time",
            value=self.process.create_time(),
        )
        ready = 0
        try:
            self.service.ready()
            ready = 1
        except Exception:
            pass
        yield GaugeMetricFamily(
            "aegis_serving_ready", "Model and governance readiness", value=ready
        )
        loaded = self.service.loaded
        if loaded is None:
            yield GaugeMetricFamily(
                "aegis_business_metrics_available", "Durable metrics query succeeded", value=0
            )
            return
        labels = [loaded.name, str(loaded.version)]
        info = GaugeMetricFamily(
            "aegis_loaded_model", "Loaded immutable model version", labels=["model", "version"]
        )
        info.add_metric(labels, 1)
        yield info
        try:
            summary = self.service.summary()
        except Exception:
            yield GaugeMetricFamily(
                "aegis_business_metrics_available", "Durable metrics query succeeded", value=0
            )
            return
        yield GaugeMetricFamily(
            "aegis_business_metrics_available", "Durable metrics query succeeded", value=1
        )
        outcome = "failure" if loaded.target == "failure" else "fraud"
        for name in (
            "predictions",
            "labeled",
            "label_coverage",
            f"predicted_{outcome}_rate",
            f"observed_{outcome}_rate",
            "precision",
            "recall",
            "f1",
            "false_positive_rate",
        ):
            metric = GaugeMetricFamily(
                f"aegis_model_{name}", "Rolling window: " + name, labels=["model", "version"]
            )
            metric.add_metric(labels, summary[name] if summary[name] is not None else math.nan)
            yield metric
        yield GaugeMetricFamily(
            "aegis_metrics_window_seconds",
            "Prediction time window",
            value=summary["window_seconds"],
        )


class ServingMetrics:
    def __init__(self, service: InferenceService):
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "aegis_http_requests_total",
            "Completed HTTP requests",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "aegis_http_request_duration_seconds",
            "End-to-end HTTP duration",
            ["method", "route"],
            registry=self.registry,
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
        )
        self.predictions = Counter(
            "aegis_predictions_total",
            "Durably recorded predictions",
            ["model", "version", "predicted_class"],
            registry=self.registry,
        )
        self.probabilities = Histogram(
            "aegis_prediction_probability",
            "Positive class probability",
            ["model", "version"],
            registry=self.registry,
            buckets=(0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1),
        )
        self.registry.register(RuntimeCollector(service))
