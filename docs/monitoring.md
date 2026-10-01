# Phase 2 monitoring

The inference process exports `/metrics`. Prometheus scrapes it every five seconds;
Grafana queries the provisioned `aegis-prometheus` datasource. API clients can also
read `/api/v1/monitoring/summary`, computed from PostgreSQL prediction events.
No production counters or chart values are hard-coded.

## Metrics

| Metric | Meaning |
| --- | --- |
| `aegis_http_requests_total{method,route,status}` | Completed HTTP requests, including validation errors |
| `aegis_http_request_duration_seconds` | End-to-end duration histogram, including durable writes |
| `aegis_predictions_total{model,version,predicted_class}` | Successfully persisted predictions |
| `aegis_prediction_probability` | Positive-class probability histogram |
| `aegis_loaded_model{model,version}` | Immutable loaded version |
| `aegis_serving_ready` | Loaded model still matches valid SQL governance |
| `aegis_business_metrics_available` | Persisted-evidence query succeeded |
| `aegis_process_cpu_seconds_total` | Actual process CPU time, on Windows/Linux |
| `aegis_process_resident_memory_bytes` | Actual resident memory |
| `aegis_model_predictions`, `aegis_model_labeled` | Evidence counts in the rolling window |
| `aegis_model_label_coverage` | Labeled / all observations |
| `aegis_model_precision`, `aegis_model_recall`, `aegis_model_f1`, `aegis_model_false_positive_rate` | Metrics computed from joined actual labels |
| `aegis_model_predicted_fraud_rate`, `aegis_model_observed_fraud_rate` | Predicted / observed positive rates |
| `aegis_metrics_window_seconds` | Window length, default 3600 seconds |

Latency p50/p95/p99 uses histogram quantiles over bucket rates: these are estimates.
The traffic script separately reports empirical client-side percentiles. CPU
seconds/second is cores consumed, not host CPU percentage.

Labels use route templates, never prediction IDs, request IDs, raw paths or features.
Unmatched routes share `unmatched`. Fraud traffic panels filter `/api/v1/predict`, so
health checks and scrapes do not inflate inference throughput. HTTP 4xx and 5xx rates
are separate. Zero errors is derived from observed traffic; no traffic is undefined.

## Evidence and restart semantics

Predictions never substitute for ground truth. Submit actual labels later with the
prediction ID. Same-label retries are no-ops; conflicting labels return 409. PostgreSQL
row locking prevents duplicate updates under concurrency. Label updates are audited.

Precision = TP/(TP+FP), recall = TP/(TP+FN), F1 = 2TP/(2TP+FP+FN), false-positive
rate = FP/(FP+TN). Undefined denominators yield JSON `null` and Prometheus `NaN`,
displayed as no data. Positive labels with zero true positives legitimately yield
zero recall/F1. Inspect label coverage: delay and selection bias affect interpretation.

The rolling window filters by **prediction creation time** and loaded model version.
Late labels for older predictions remain stored but do not affect the current window.
SQL-derived counts are gauges, survive restarts and decrease as observations expire.
Process counters/histograms reset on restart; Prometheus `rate` handles counter resets.

Database failures omit business metrics rather than presenting stale values as fresh.
A timed-out scrape yields Prometheus `up=0`. Readiness, reachability and evidence
availability are independent signals on the dashboard.

## Provisioning

Files live in `infrastructure/prometheus` and `infrastructure/grafana`. Generate dashboard
JSON with `python scripts/build_dashboard.py`. Grafana provisioning overrides UI edits.
Native/container addresses are supplied through configuration/environment variables.

The 14 panels cover health, version, throughput, request counts, latency, errors,
prediction distribution, probability distribution, model performance, label evidence,
fraud rates, CPU and memory. Prometheus retains seven days of local time series.
SQL events retain allowlisted feature values for later reliability analysis; automated
retention/partitioning is not implemented yet.

This stack supports one inference process/worker. Multiple replicas' SQL evidence
gauges must not be summed: they would represent the same underlying data. Distributed
metrics aggregation is deferred.

## Verification

`python scripts/traffic.py --count 300 --rate 15 --concurrency 8 --labels --invalid-every 20`
sends real HTTP traffic using held-out synthetic transactions, then submits labels.
Every twentieth request has an invalid hour and produces a real 422 response.
No data is inserted directly into metrics storage.

After a scrape, run `python scripts/verify_phase2.py`. It checks readiness, evidence
equality, target health, every dashboard PromQL expression and Grafana's datasource
proxy. It requires recent traffic/labels and no concurrent writes during its snapshot.

Drift, severity policies and incident creation belong to Phase 3. Dashboard values
and HTTP errors do not create Aegis incidents yet.

References: [Prometheus collectors](https://prometheus.github.io/client_python/collector/custom/),
[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/).
# Phase 3 reliability evidence

In addition to time-series monitoring, run `aegis reliability evaluate` against a
version-specific serving window or upstream batch. Profiles, drift/performance
evidence, severity and incidents are stored in PostgreSQL; they are not fabricated
Prometheus samples. See [reliability operations](reliability.md) for commands and
policy semantics. The existing Grafana dashboard remains the fraud serving dashboard.
