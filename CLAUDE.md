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

## Changelog

`frontend/CHANGELOG.md` is updated as part of every `dev` → `master` promotion
(via the `release-dev-to-master` skill), not on an ad hoc daily basis. The
skill adds a new `## YYYY-MM-DD` section summarising everything that shipped
since the previous changelog entry, grouped into **Features**, **Fixes**, and
**Chores**, reconstructed from `git log --oneline <last-date-sha>..dev`. The
changelog commit lands on `master` as part of the same merge, with message
`docs: update changelog YYYY-MM-DD`, and is immediately cherry-picked onto
`dev` too so the two branches' changelog never diverges.

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
