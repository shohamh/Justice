# GitLab CI/CD validation pipeline

The pipeline runs for merge requests and branch commits. When a branch has an
open merge request, the merge request pipeline takes precedence over the
duplicate push pipeline. Other pipeline sources are excluded. The reserved
stages are `validate`, `test`, `build`, and `publish-mock`; validation and test jobs exist so far. Later stages must depend on successful validation and
tests before any disposable registry publication. There are no deployment or
release jobs, production variables, or real registry pushes in this pipeline (only the job-scoped mock registry).

## Validation jobs

| Job | Checks |
| --- | --- |
| `backend-validate` | Installs the locked backend development dependencies, then runs Ruff lint, Ruff format check, and mypy. |
| `frontend-validate` | Runs `npm ci`, lint, and typecheck from `frontend/`. |
| `compose-validate` | Parses the base app Compose file and the base file merged with the Task 8 E2E overlay. It does not start containers. |

## Test jobs

| Job | Checks |
| --- | --- |
| `backend-test` | Runs `uv run pytest -q` (the primary suite; slow CP-SAT scenarios stay deselected) against a job-scoped `docker:dind` service that testcontainers uses for Postgres and Redis. Needs `backend-validate`. |
| `frontend-test` | Runs `npm ci` and `npm test` (Vitest). Needs `frontend-validate`. |

| `backend-test-slow` | Runs `uv run pytest --slow -q` (large CP-SAT scenarios, up to 1h). On schedules it runs automatically; otherwise it is a manual, non-blocking job. Run it before a release. |
| `e2e` | Starts Postgres (service), migrates, seeds, serves backend and a built frontend, then runs Playwright on Chrome: smoke on merge requests, full suite otherwise. Needs both test jobs; the report is kept for a week on failure and contains only seeded synthetic data. |

`backend-test` runs the same paths as the GitHub workflow (`tests`,
`app/services/hr/tests`, `app/tests`, excluding `test_candidate_rank.py`).
Image build jobs also need `e2e`. `backend-test` requires a runner that allows privileged services (Docker or
Kubernetes executor with `privileged = true`). Ryuk is disabled because the
dind daemon is discarded with the job.

## Build and mock publish

| Job | Checks |
| --- | --- |
| `backend-image` | Builds the backend `production` image. Needs both test jobs and `compose-validate`. |
| `frontend-image` | Builds the frontend `runtime` image. Same needs. |
| `publish-mock` | Rebuilds both images, pushes them to a job-scoped `registry:2` service, then removes and pulls them back to prove the round trip. |

Images are tagged with `$CI_COMMIT_SHORT_SHA` and are never pushed outside the
job. The build jobs need the same privileged Docker-in-Docker capability as
`backend-test`. `publish-mock` rebuilds rather than reusing the build jobs'
images because each job gets its own throwaway daemon; sharing would require
an artifact tarball, which is deliberately avoided.

The frontend cache contains only npm's download cache at `frontend/.npm/`,
keyed by `frontend/package-lock.json`. The job still runs `npm ci` each time;
`node_modules` is neither cached nor transferred as an artifact. This
validation-only pipeline currently uploads no artifacts. Any later browser
artifacts or traces must contain only synthetic seeded data.

The Compose job uses `--no-env-resolution` because the fresh checkout does not
contain local secret env files. Docker Compose still parses the Compose model.
The Task 8 overlay uses `!override` and `!reset`; [Docker Compose 2.24.4 or
newer](https://docs.docker.com/reference/compose-file/merge/#replace-value)
is required. The job image includes Compose 2.33.0 and reports an
actionable error if parsing fails. The validation job itself does not need a
Docker daemon. Later image builds and disposable registry tests need a
Docker-compatible daemon/build service. [Docker-in-Docker on GitLab](https://docs.gitlab.com/ci/docker/docker_in_docker/)
requires a privileged Docker or Kubernetes runner, so runner operators must explicitly
provide that capability for those later jobs. The registry endpoint must be a
job-scoped disposable service and must never point to configured Artifactory.
No production secrets belong in these jobs: a fork merge request run in the
parent project can receive [configured CI variables](https://docs.gitlab.com/ci/variables/)
in some GitLab setups.

## Run locally

From the repository root, with Docker Compose 2.24.4 or newer:

```sh
docker compose -f docker-compose.yml config --no-env-resolution --quiet
docker compose -f docker-compose.yml -f docker-compose.task8-e2e.yml config --no-env-resolution --quiet
```

From `backend/`, with Python 3.12 and uv:

```sh
uv sync --locked --extra dev
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
```

From `frontend/`, with Node.js 22 and npm:

```sh
npm ci
npm run lint
npm run typecheck
```

The primary backend test suite is `uv run pytest -q`; it requires Docker for
testcontainers. The full release gate is `uv run pytest --slow -q`, which
includes the large CP-SAT scenarios and is substantially slower. The `test` stage runs the primary suite only.

GitLab's [CI Lint](https://docs.gitlab.com/ci/yaml/lint/) should be run against the pipeline configuration in the
target GitLab project before enabling runners. YAML parsing alone cannot
confirm GitLab-specific `workflow`, cache, or job semantics.
