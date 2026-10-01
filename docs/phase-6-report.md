# Phase 6 implementation and validation

ATLAS now includes a public landing page, visible development credentials, a login
page, scroll-driven CSS 3D lifecycle, and ten live operations workspaces. Signed
sessions protect the console proxy; operator credentials stay server-side. The
backend implements persisted canary traffic, fresh measured health gates,
progressive promotion, manual/automatic rollback, and deployment audit history.

## Executed validation (23 September 2026)

- Final source-bound validation passed: 91 unit tests and 16 integration tests,
  including real PostgreSQL concurrency and real MLflow classification/regression
  rollout tests. Ruff lint, formatting and dependency checks passed.
- An earlier coverage run reported 84%; its one PostgreSQL setup error occurred
  during a local database outage. After recovery all 104 pre-fix tests passed. Coverage
  from the interrupted run is informational, not a clean final coverage claim.
- Next.js production build and TypeScript checking passed. npm production audit
  found zero vulnerabilities.
- Browser inspection at 1440x900 and 390x844 verified the landing page, 3D scene,
  mobile layout, login, invalid-credential error, autofill, navigation and logout.
  Scroll changes the scene transform; mobile has no horizontal page overflow.
  Unauthenticated workspace navigation redirects to login. No browser errors were
  observed. Reduced-motion styling and skip navigation are implemented.
- HTTP checks passed for anonymous access rejection, cross-origin login rejection,
  incorrect password rejection, signed HttpOnly/SameSite session creation,
  authenticated state reads and rejection of a tampered cookie.
- Control API, original inference, Prometheus and Grafana returned HTTP 200 readiness.
- Kubernetes, kind and GitHub Actions configuration parsed successfully as YAML.

Final verification ID: `25b8e231-1ff8-40b6-8bb5-10376c93ae5d`.
Source hash: `4a18e086e998ffb0619817786604338aa214f93d46c5ff8f18ace60611d0ab13`.
The persisted VerificationRun contains command summaries and output digests.

## Live exercise finding

The first real canary sent 877 requests, including 100 labeled candidate calls.
It had zero errors, p95 13.77 ms, F1 0.906 and recall 0.96, but progression stayed
blocked because timestamp handling produced a negative observation age for
PostgreSQL session-local timestamps. The controller now preserves aware offsets
and treats only naive SQLite timestamps as UTC. Three regression cases cover UTC,
UTC+05:30 and naive UTC. The first exercise was explicitly rolled back before retry.

## Explicit runtime limits

Docker Desktop's Linux engine pipe was unavailable after startup, and kind was not
installed on this machine. Kubernetes manifests, version-runtime provisioning and
CI smoke coverage are implemented, but no successful local kind deployment or
remote GitHub Actions execution is claimed. The authored Playwright CI suite was
not executed locally; interactive browser and HTTP checks above were executed.

KServe and shadow traffic remain optional future adapters. Kubernetes uses standard
Deployments/Services. The native demo is fully local; this shared demo login and
single-process router are not production identity or high-availability infrastructure.
See [rollout operations](rollouts.md), [console operations](control-plane.md), and
[ADR 006](adr/006-control-plane-and-rollouts.md).

## Successful real HTTP rollout

Deployment `8b0e3c6b-9dd5-4bc3-83fd-d7f4246e6d73` for `maintenance-rollout-demo`
passed every measured stage, promoted, then completed explicit rollback. A final
HTTP prediction confirmed the previous version served again.

| Traffic | HTTP requests | Candidate labels | p95 ms | F1 | Recall | Health |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 10% | 908 | 100 | 14.20 | 0.842 | 0.960 | HEALTHY |
| 25% | 369 | 100 | 15.25 | 0.681 | 0.727 | HEALTHY |
| 50% | 223 | 100 | 16.75 | 0.857 | 0.960 | HEALTHY |
| 100% | 100 | 100 | 18.02 | 0.754 | 0.742 | HEALTHY |

All stages had zero recorded errors. The routing split is probabilistic; the
script stops each stage after 100 candidate labels. These are synthetic validation
requests using the explicitly scoped demo policy, not production traffic.
Evidence: `data/deployment/phase6-demo/results.json`, SQL deployments, routing events
and audit history. The three original workload approvals were not changed.
