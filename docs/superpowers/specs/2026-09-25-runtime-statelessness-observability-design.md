# Runtime statelessness + observability — design

Date: 2026-09-25
Branch/worktree: `feature/scalability-and-openshift`
Status: approved by user, pending implementation plan

## Context

This is the first of a planned series of independent sub-projects toward
horizontal-scaling and OpenShift readiness:

- **A+E (this doc):** stateless backend audit + observability (logs → Loki,
  metrics → Prometheus, dashboards → Grafana)
- **B (future):** S3-compatible file storage (MinIO in dev, S3 API in prod)
- **C (future):** DB transaction/concurrency audit across `backend/app/services/*`
- **D (future):** GitLab CI/CD (test + docker build + push to a mocked
  Artifactory)

Each gets its own spec → plan → implementation cycle. This document covers
A+E only.

## Motivation

The backend currently keeps several kinds of state in process memory. That's
invisible today because there's exactly one backend process in dev and one
in the current production deployment, but it silently breaks the moment a
second replica or worker process is added — a prerequisite for horizontal
scaling. Separately, the user wants standard log/metrics tooling (Loki,
Prometheus, Grafana) usable both to test the app locally end-to-end and,
eventually, on OpenShift — where the operational model differs from today's
Docker Compose setup (no reliable local disk per pod, cluster-provided
logging/monitoring stack, `ServiceMonitor` CRDs instead of static scrape
configs).

## Goals

1. Eliminate in-process state that breaks under >1 replica/worker, or
   replace it with a shared backend (Redis).
2. Ship backend logs to Loki (both in local dev and, eventually, OpenShift)
   without depending on cluster-logging infrastructure we don't control.
3. Expose Prometheus-format metrics.
4. Make the admin errors page read from Loki instead of local log files,
   including a Loki-compatible replacement for the current hard-delete
   "clear" action.
5. Give the dev stack a working Grafana + Loki + Prometheus setup so this is
   verifiable end-to-end locally, not just asserted.
6. Provide illustrative OpenShift manifests for how this looks in that
   environment.
7. Document the resulting system architecture with a services diagram.

## Non-goals

- Actually deploying Loki/Prometheus/Grafana on a real OpenShift cluster —
  that belongs to the future Kubernetes repo built on the company network.
- Implementing Loki's Compactor-based hard-delete API.
- The other three sub-projects (B, C, D) listed above.
- A full audit of *every* possible piece of shared mutable state in the
  codebase beyond what's enumerated below — new instances found later can be
  fixed the same way, but this plan targets the known ones.

## Known findings (audit checklist / starting point)

| Location | State | Problem | Fix |
|---|---|---|---|
| `backend/app/rate_limit.py:7` | slowapi `Limiter` with default `MemoryStorage` | Per-process request counters — rate limits don't apply across replicas/workers | `storage_uri="redis://..."` |
| `backend/app/services/algorithm_bridge.py:53` | `_cancel_events: dict[str, threading.Event]` | Cancel request landing on a different replica than the one running the solver job silently no-ops | Move to Redis (e.g. a key per job id that the running worker polls, or pub/sub) |
| `backend/app/services/gimelim.py:36` | `_PREVIEW_STORE: dict[str, tuple[datetime, dict]]` | Same replica-affinity problem; manual TTL reimplements what Redis does natively | Move to Redis with `EX` TTL |
| `backend/app/error_logging.py:30` | `_rate_limit_state` (burst-suppression for duplicate error logs) | Same category, but best-effort/non-correctness-critical | Flag in the plan; leave as-is unless it's cheap to also move |
| `backend/app/logging_config.py` | `RotatingFileHandler` writing to local disk (`LOG_DIR`) | No persistent local disk per pod in OpenShift; also what `admin_errors.py` reads from | Replace with a Loki push handler (see below) |

The implementation plan should include a step that greps for the same
patterns (module-level mutable `dict`/`set`/`list` used as a cache or
registry, `threading.Lock`-guarded globals) to catch anything not listed
here, but is not expected to turn up much more given what this exploration
already found.

## Logging: direct push to Loki, not DaemonSet scraping

Standard OpenShift practice is for a node-level DaemonSet (Promtail/Vector,
usually via the cluster's own Loki Operator) to tail pod stdout and ship it
to Loki, with the app knowing nothing about Loki. We are **not** doing that
here, because the OpenShift cluster and its logging stack are managed on a
different network/team, and we have no guarantee that infrastructure will
exist or be configured the way we need by the time this ships.

Instead: `logging_config.py` gains a logging handler that pushes JSON
records directly to Loki's HTTP push API (`POST /loki/api/v1/push`), pointed
at a `LOKI_URL` env var. This is:

- Environment-agnostic — identical code path whether the backend runs
  natively via `dev.ps1`, in docker-compose, or as an OpenShift pod.
- Simpler to test locally (point `LOKI_URL` at the new dev Loki container).
- Decoupled from local disk — the existing `RotatingFileHandler` is removed
  from the default path (fixing the statelessness problem and the
  admin-errors dependency at the same time). It may remain available as an
  explicit opt-in fallback for offline local debugging, gated behind its own
  env var, but is off by default.

Labels pushed with each log stream: at minimum `app="justice-backend"` (or
`justice-bot` for the Telegram bot process), `env`, and `level`, so Loki
queries in `admin_errors.py` can filter efficiently.

## Metrics

Add `prometheus-fastapi-instrumentator`, exposing `/metrics` in Prometheus
text format (request rate/latency/status by route, plus default
process/Python metrics). This is what both the dev Prometheus's static
scrape config and the example OpenShift `ServiceMonitor` target.

## Dev docker-compose additions

New services in `docker-compose.yml` (or a separate compose file merged in,
if that keeps the base file cleaner — decide during planning):

- `loki` — official image, minimal local config (filesystem storage is fine
  for dev).
- `prometheus` — scrapes the backend's `/metrics` and its own targets.
- `grafana` — pre-provisioned (via mounted provisioning files, not manual
  UI clicks) with the Loki and Prometheus datasources already wired up, and
  one starter dashboard showing recent error-level logs plus basic request
  metrics, so `docker compose up` produces something to look at immediately
  without manual Grafana setup.

No Promtail service is needed given the direct-push logging approach above.

## Admin errors page migration

`error_logs.py` (the module `admin_errors.py` currently calls into) is
rewritten to query Loki (`GET /loki/api/v1/query_range`) instead of parsing
local files, keeping the same `ErrorLogEntryOut`/`PaginatedErrorLogsOut`
response shapes so the frontend (`ErrorsContent.tsx`) needs no changes.

`DELETE /admin/errors` (currently a real delete through a timestamp) becomes
a **soft clear**: instead of removing log data, it records a per-admin
"cleared before" timestamp (new column or table alongside the existing
`AdminErrorRead`), and `list_admin_errors`/`admin_error_unread_count` filter
out anything at or before that timestamp for the requesting admin. This
matches the existing per-admin read-tracking model already in place and
avoids needing Loki's Compactor delete API.

## Example OpenShift manifests

Add `deploy/openshift/examples/` containing illustrative, clearly-commented
YAML: `Deployment`, `Service`, `ServiceMonitor` (pointing at `/metrics`),
and `HPA` (scaling on CPU or request rate). These are starting points for
whoever builds the real Kubernetes repo later on the company network, not
manifests we expect to `oc apply` ourselves from this repo.

## Architecture documentation

Add `docs/architecture.md` (or update it if something like it already
exists — check during planning) describing the resulting system, plus a
services diagram (Mermaid, so it renders in GitHub/GitLab without extra
tooling) showing: frontend, backend (N replicas), Telegram bot, Postgres,
Redis, Loki, Prometheus, Grafana, and — as a separate, clearly-labeled
"future/example" section — the OpenShift-side pieces (Deployment/Service/
ServiceMonitor/HPA) from the manifests above. This should reflect the
actual end state of this sub-project, so it's written last, once the rest
of the implementation is in place.

## Testing

- Unit/integration tests for the Redis-backed rate limiter, cancel-event
  store, and preview store (replacing whatever tests currently exercise the
  in-memory versions).
- Integration test(s) for the Loki push handler (can run against a
  real Loki test container if the existing test suite already uses
  testcontainers-style fixtures for Postgres; otherwise mock the HTTP call
  at the boundary).
- Integration tests for the rewritten `admin_errors.py` endpoints against a
  Loki test instance/fixture, including the soft-clear semantics.
- Manual/documented verification step: bring up the full dev docker-compose
  stack, trigger a backend error, and confirm it's visible in both the
  admin errors page and Grafana/Loki directly.

## Open questions for planning (not blocking, but flag during plan-writing)

- Where Redis fits in `docker-compose.prod.yml` / the future OpenShift
  manifests (single instance is fine for now — no need for Redis Cluster/
  Sentinel at current scale).
- Exact schema change needed for the per-admin "cleared before" timestamp
  (new column on `AdminErrorRead`'s table vs. a new small table) — decide
  during plan-writing by looking at the existing model.
