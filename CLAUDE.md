# Project: justice

Army duty management system. Hebrew UI, English code. See README.md for full context.

## Starting the dev stack

```powershell
.\dev.ps1                 # backend + frontend (default)
.\dev.ps1 -TelegramBot   # include the Telegram bot
```

This script:
- Keeps Postgres in Docker, runs everything else natively on Windows
- Stops any running Docker app containers first (frees ports 8000 / 5173)
- Creates `backend\.venv` (Python venv) on first run and installs all deps via pip
- Waits for DB health, runs Alembic migrations, then launches all services via `concurrently`
- All logs stream in one terminal with colored `[backend]` / `[frontend]` / `[bot]` prefixes
- Ctrl+C stops all services cleanly

**Do not** use `docker compose up` for day-to-day dev — Docker Desktop's volume
file-watching on Windows misses events, breaking hot reload.

**Using a private PyPI mirror:** set `PIP_INDEX_URL=https://your.mirror/simple/` in your
shell or in `.env` before running `dev.ps1`. pip reads this variable automatically.
Delete `backend\.venv` to force a reinstall against the new index.

## Key URLs (local dev)

| Service  | URL                            |
|----------|--------------------------------|
| Frontend | http://localhost:5173          |
| Backend  | http://localhost:8000/docs     |

## Repo layout (short)

```
backend/app/
  routes/     REST endpoints + Pydantic schemas
  services/   business logic
  algorithm/  pure CP-SAT solver (no DB imports)
  auth/       JWT + RBAC
  db/         SQLAlchemy models + Alembic migrations
frontend/src/
  api/        typed fetch wrappers
  pages/      page components
  components/ shared UI
```

## Branch workflow

- Feature branches (including worktrees) branch off `dev`, small per-task commits
- Finished work merges into `dev` first — never directly into `master`. Use the
  project skill `merge-worktree-to-dev` (instead of the generic
  `finishing-a-development-branch` flow) to do this.
- `dev` is periodically promoted to `master` (a "release"). Use the project
  skill `release-dev-to-master` for this — it merges `dev` into `master` and
  updates the changelog in the same step (see below).
- Do NOT commit directly to `master` or `dev`

## Implementing written plans

If a superpowers plan has been written for the task (e.g. via `writing-plans`),
always execute it with subagents (`subagent-driven-development` or
`executing-plans`) rather than implementing it directly in the main
conversation.

## Changelogs

Two changelogs, two audiences:

- `docs/CHANGELOG-dev.md` — **developer-facing**. Every merge into `dev` (via
  the `merge-worktree-to-dev` skill) adds an entry under `## Unreleased`:
  modules touched, migrations, API changes, gotchas, and a `Docs:` line
  pointing at the plan/spec for the change.
- `frontend/CHANGELOG.md` — **user-facing**. Written during every `dev` →
  `master` promotion (via `release-dev-to-master`) from the dev changelog's
  `## Unreleased` section plus the plan/design docs it references. New
  `## YYYY-MM-DD` section, grouped **Features** / **Fixes**, plain language,
  with a "Why:" rationale for non-obvious changes (none for simple bug fixes).
  The skill also renames `## Unreleased` in the dev changelog to the release
  date. The commit lands on `master` as `docs: update changelog YYYY-MM-DD`
  and is immediately cherry-picked onto `dev` so the branches never diverge.

## Common one-liners

```bash
# Backend — activate venv first: backend\.venv\Scripts\activate (Windows)
pytest -q                          # fast suite, parallel by default (-n auto baked into addopts; ~1.5 min)
pytest --slow -q                   # EVERYTHING incl. the 8 large-scale CP-SAT tests (~11 min added) — run before a release (CI skips slow)
pytest -m algorithm -q             # just one system area: algorithm | auth | hierarchy | duty | scoring | notifications | soldiers | misc
pytest -m "duty or scoring" -q     # combine areas
alembic revision -m "description"  # new migration
alembic upgrade head               # apply migrations

# Add/update Python deps (from backend/):
pip install -e ".[dev]"            # reinstall after editing pyproject.toml

# Frontend (run from frontend/)
npm test           # vitest unit tests
npm run lint       # eslint (zero warnings enforced)
npm run typecheck  # tsc --noEmit (not run by lint — run separately, or rely on CI)
```
