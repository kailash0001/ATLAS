# Fraud inference API

Use `python scripts/dev.py api`, the Compose `serving` profile, or
`python scripts/native_observability.py up`. The API is on localhost:8000 with
OpenAPI at `/openapi.json` and interactive docs at `/docs`.

## Loading and readiness

Startup requires migration `0002`, one SQL champion, FINISHED training lineage,
matching environment and `sync_pending=false`. The loader verifies MLflow's alias/run
ID, downloads the immutable version and checks feature signature, dataset fingerprint
and saved threshold. The artifact includes fitted preprocessing. Governance is
rechecked after downloading.

A failed load leaves the HTTP process alive but unready. Correct the dependency and
restart; there is no fallback model. Liveness is separate from readiness. New predictions
check SQL governance: promotion or pending alias sync makes the old model unready until
restart. Requests admitted before a concurrent promotion can finish on their original
version, which is recorded in their responses/events.

MLflow outages after loading do not invalidate the cached immutable artifact. SQL must
remain available. Direct MLflow alias changes are unsupported; use Aegis governance.

| Route | Behavior |
| --- | --- |
| `GET /health/live` | Process liveness |
| `GET /health/ready` | Governed model readiness, or 503 |
| `POST /api/v1/predict` | One transaction, persisted before returning 200 |
| `PUT /api/v1/predictions/{prediction_id}/label` | Idempotent actual-label submission |
| `GET /api/v1/model` | Loaded version, features, threshold |
| `GET /api/v1/monitoring/summary` | Persisted evidence and observed metrics |
| `GET /metrics` | Prometheus exposition |

## Example

```powershell
$features = @{
  amount = 25.0; hour = 12; distance_from_home = 5.0
  transactions_24h = 2; account_age_days = 300
  merchant_category = 'grocery'; card_present = 'yes'
} | ConvertTo-Json
$prediction = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/predict `
  -ContentType application/json -Body $features -Headers @{'X-Request-ID'='example-001'}
$prediction
# Only after actual ground truth is available:
Invoke-RestMethod -Method Put `
  -Uri "http://127.0.0.1:8000/api/v1/predictions/$($prediction.prediction_id)/label" `
  -ContentType application/json -Body '{"actual_label":0}'
```

Responses include event/request IDs, model name/version, probability, class and threshold.
Headers include `X-Request-ID`, `X-Model-Name` and `X-Model-Version`. All feature keys
are required. Explicit numeric nulls use the trained imputer; unseen merchant categories
use the trained encoder. Invalid types/ranges, extra keys, target leakage and NaN/Infinity
are rejected. The default body limit is 16 KiB, including streamed bodies.

## Durability and failures

Events store immutable model-version FK, timestamp, request ID, allowlisted features,
probability, class, threshold and inference duration. Persistence failure returns 503.
Request IDs are correlation IDs, not idempotency keys; retries after uncertain delivery
can create additional prediction events. Label retries are idempotent, conflicts are
409, unknown IDs are 404, and changes are audited under the configured local actor.

Errors use `{ "error": { "code", "message", "request_id" } }`. Codes include
INVALID_REQUEST (422), PAYLOAD_TOO_LARGE (413), OVERLOADED (429), INFERENCE_FAILED
(500), and readiness/database/telemetry failures (503). Error bodies and structured
request logs exclude financial features. Logs include request/event identity, route
template, status, duration and model version. Uvicorn lifecycle messages remain separate.

External I/O has database connect/statement/lock and MLflow HTTP timeouts. Model
execution is in-process with bounded concurrency, not forcibly terminated by a hard
deadline. Uvicorn's transport-level overload responses occur before app middleware and
therefore may lack app headers/counters. One worker is supported in this phase.

## Settings and boundaries

Settings inherit the existing database/tracking/environment/actor variables. Additional
environment or `.env` settings are:

| Setting | Default |
| --- | --- |
| `AEGIS_SERVING_MODEL` | `fraud-detector` |
| `AEGIS_METRICS_WINDOW_SECONDS` | `3600` |
| `AEGIS_MAX_REQUEST_BYTES` | `16384` |
| `AEGIS_SERVING_DATABASE_TIMEOUT_SECONDS` | `5` |
| `AEGIS_SERVING_MAX_CONCURRENCY` | `32` |

Local-only operation has no authentication, TLS, background model reload or automatic
rollout. Labels are trusted local input, with no authenticated external label source.
The synthetic baseline's low recall remains visible; serving does not imply production
fraud approval. Label correction, event retention and distributed serving are deferred.
# Phase 3 workload extension

The same service now accepts either the fraud contract or the maintenance contract,
and rejects payloads that do not match its loaded model. A process still serves one
governed champion. Maintenance uses `predicted_failure_rate` and
`observed_failure_rate` in the summary and corresponding `aegis_model_*` gauges;
fraud names remain unchanged. See [maintenance serving and example payload](reliability.md)
for the optional port-8001 process and physical sensor bounds. Add a separate
Prometheus scrape target for that process if running it alongside fraud.
