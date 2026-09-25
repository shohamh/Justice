# OpenShift examples

Illustrative starting points for whoever builds the real Kubernetes/OpenShift
repo on the company network — **not** manifests this repo expects to `oc
apply` directly. Placeholders to fill in for a real deployment:

- `deployment.yaml`'s `image:` — the tag pushed to Artifactory by the CI/CD
  pipeline (see the future GitLab CI sub-project).
- `justice-backend-secrets` — a real Secret holding `DATABASE_URL`/`REDIS_URL`
  for that environment.
- The `LOKI_URL` value — wherever Loki actually lives on that cluster
  (this app pushes to it directly over HTTP; see
  `docs/superpowers/specs/2026-09-25-runtime-statelessness-observability-design.md`
  for why).
- `servicemonitor.yaml` requires the Prometheus Operator CRDs to exist on the
  target cluster — confirm before applying.

None of this configures Loki/Prometheus/Grafana themselves — that's assumed
to already exist on the cluster (platform-managed), or to be added by the
future Kubernetes repo.
