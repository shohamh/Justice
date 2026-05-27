# Call of Duty 2 — Army Duty Management System

Self-hostable system for assigning duties (תורנויות) to soldiers fairly,
with audit-logged manual workflows in v1 and a fairness-aware CP-SAT
algorithm in v1.5+. See [the design doc](docs/superpowers/specs/2026-05-27-army-duty-management-design.md).

## Quick start (dev)

1. Copy `.env.example` to `.env` and review the values.
2. `docker-compose up -d db` to start Postgres.
3. `cd backend && uv sync && uv run alembic upgrade head`
4. `uv run python -m app.scripts.bootstrap` (creates the first admin).
5. `uv run uvicorn app.main:app --reload --port 8000`
6. `cd ../frontend && pnpm install && pnpm dev`
7. Open http://localhost:5173, log in with the bootstrap admin credentials.

## Repo layout

- `backend/` — FastAPI app + Alembic migrations + tests
- `frontend/` — Vite + React + TS SPA + e2e tests
- `docs/` — design docs and implementation plans
- `ops/` — deployment scripts (added in slice 7)
