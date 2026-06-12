# Project: callofduty2

Army duty management system. Hebrew UI, English code. See README.md for full context.

## Starting the dev stack

```powershell
.\dev.ps1        # backend + frontend + Telegram bot (default)
.\dev.ps1 -NoBot # skip the bot
```

This script:
- Keeps Postgres in Docker, runs everything else natively on Windows
- Stops any running Docker app containers first (frees ports 8000 / 5173)
- Waits for DB health, runs Alembic migrations, then launches all services via `concurrently`
- All logs stream in one terminal with colored `[backend]` / `[frontend]` / `[bot]` prefixes
- Ctrl+C stops all services cleanly

**Do not** use `docker compose up` for day-to-day dev — Docker Desktop's volume
file-watching on Windows misses events, breaking hot reload.

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

- Feature branches off `master`, small per-task commits
- Do NOT commit directly to `master`

## Common one-liners

```bash
# Backend (run from backend/)
uv run pytest -q                          # fast suite (excludes @pytest.mark.slow; serial)
uv run pytest -n 8 -q                     # fast suite in parallel (each xdist worker gets its own throwaway Postgres container)
uv run pytest -m slow -q                  # only the 8 large-scale CP-SAT tests (~11 min)
uv run pytest -m "slow or not slow" -n 8  # EVERYTHING (slow + fast) in parallel — use in CI
uv run alembic revision -m "description" # new migration
uv run alembic upgrade head               # apply migrations

# Frontend (run from frontend/)
pnpm test    # vitest unit tests
pnpm lint    # eslint (zero warnings enforced)
```
