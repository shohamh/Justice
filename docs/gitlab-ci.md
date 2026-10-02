# GitLab CI/CD validation pipeline

The pipeline runs for merge requests and branch commits. When a branch has an
open merge request, the merge request pipeline takes precedence over the
duplicate push pipeline. Other pipeline sources are excluded. The reserved
stages are `validate`, `test`, `build`, and `publish-mock`; this first step only
adds validation jobs. Later stages must depend on successful validation and
tests before any disposable registry publication. There are no deployment or
release jobs, production variables, or registry pushes in this pipeline.

## Validation jobs

| Job | Checks |
| --- | --- |
| `backend-validate` | Installs the locked backend development dependencies, then runs Ruff lint, Ruff format check, and mypy. |
| `frontend-validate` | Runs `npm ci`, lint, and typecheck from `frontend/`. |
| `compose-validate` | Parses the base app Compose file and the base file merged with the Task 8 E2E overlay. It does not start containers. |

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
includes the large CP-SAT scenarios and is substantially slower. Neither test
suite is part of this validation-only step; the `test` stage is reserved for
the next implementation tasks.

GitLab's [CI Lint](https://docs.gitlab.com/ci/yaml/lint/) should be run against the pipeline configuration in the
target GitLab project before enabling runners. YAML parsing alone cannot
confirm GitLab-specific `workflow`, cache, or job semantics.
