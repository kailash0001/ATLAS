# ADR 006: ATLAS control plane and measured rollouts

Status: implemented; local kind execution requires a working container engine.

Use a Next.js console backed by a FastAPI control API and SQL-governed routing state.
Keep Next.js operator credentials server-side and expose a shared local demo login.
Retain the existing Python package and infrastructure names for compatibility.

Use native cached MLflow predictors for the Windows demo and standard Kubernetes
Deployments/Services for immutable version runtimes on kind. Both use the same rollout
state machine and health policy. KServe remains an optional future adapter: installing
its additional gateway/controller dependencies is unnecessary for this bounded local
control-plane implementation. Shadow traffic is optional and is not implemented.

The controller records real request outcomes and labels by epoch; it does not advance
on elapsed time alone. SQL is authoritative for traffic and champion state. MLflow
alias updates are retryable rather than falsely reported as atomic with SQL.

Consequences: the local router is a single control-process service, not a production
high-availability gateway. Prometheus availability and Kubernetes runtime validation
are reported separately from native rollout tests. Production identity, distributed
routing, shared artifact storage and ingress hardening require a deployment-specific
follow-up rather than being implied by the local demo.

References: https://kind.sigs.k8s.io/docs/user/quick-start/ and
https://kserve.github.io/website/docs/0.17/admin-guide/kubernetes-deployment .
