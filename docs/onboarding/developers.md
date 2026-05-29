# Developer Onboarding

For humans setting up the project and contributing code. AI agents should also
read [agents.md](agents.md).

- [Prerequisites](#prerequisites)
- [First-time setup](#first-time-setup)
- [Windows gotchas](#windows-gotchas)
- [Running & developing](#running--developing)
- [Codebase tour](#codebase-tour)
- [Conventions](#conventions)
- [Testing](#testing)
- [Database & migrations](#database--migrations)
- [How to add a feature](#how-to-add-a-feature)

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker | any recent | runs Postgres; also required for backend integration tests (testcontainers) |
| Python | 3.12 | managed via [uv](https://docs.astral.sh/uv/) |
| uv | ≥ 0.4 | backend dependency & venv manager |
| Node | 20 | frontend |
| pnpm | 9 | frontend package manager |

---

## First-time setup

```bash
# from the repo root
cp .env.example .env

docker-compose up -d db          # Postgres 16 on :5432

cd backend
uv sync --extra dev              # installs runtime + dev deps into .venv
uv run alembic upgrade head      # creates the `app` DB role + all tables
uv run python -m app.scripts.bootstrap   # first admin from BOOTSTRAP_ADMIN_* env
uv run python -m app.scripts.seed        # OPTIONAL: realistic demo data
uv run uvicorn app.main:app --reload --port 8000

cd ../frontend
pnpm install
pnpm dev                         # http://localhost:5173
```

The backend listens on `:8000`, the SPA on `:5173`, and the SPA talks to the API
at `VITE_API_BASE` (default `http://localhost:8000/api`).

### Two Postgres roles
- `db_admin` (from `docker-compose.yml`) — superuser-ish; used for migrations and
  backups. `DB_ADMIN_URL` in `.env`.
- `app` — the restricted role the FastAPI process logs in as. **Created by Alembic
  migration `0001`**, not by Docker — so you must run `alembic upgrade head`
  before the app can connect. `DATABASE_URL` in `.env`.

---

## Windows gotchas

This repo is developed on Windows 11. Things that cost time to rediscover:

- **Run backend commands from `backend/`.** `uv run …` needs the project root;
  invoking it from the repo root fails to find the project. If a shell's cwd
  drifts, `cd backend` first.
- **pnpm isn't on PATH by default** and `corepack enable` needs admin rights on
  `C:\Program Files\nodejs`. It was installed via `npm install -g pnpm@9`
  (user prefix `C:\Users\<you>\AppData\Roaming\npm`).
- **Two `.env` files.** The backend reads the **repo-root `.env`** (resolved by
  absolute path in [`settings.py`](../../backend/app/settings.py)). **Vite does
  not** read the root `.env` — if you need to override `VITE_API_BASE`, create
  `frontend/.env`.
- **Docker must be running** for backend tests (testcontainers spins up a real
  Postgres per run) and for the local `db` service.
- PowerShell is the default shell — use `$env:VAR` / `$null`, not bash syntax,
  for one-off commands.

---

## Running & developing

```bash
# Backend (from backend/)
uv run uvicorn app.main:app --reload --port 8000

# Frontend (from frontend/)
pnpm dev
```

There is **no Swagger UI**: `create_app()` sets `docs_url=None`, `redoc_url=None`,
`openapi_url=None`. To explore the API, read the route modules under
[`backend/app/routes/`](../../backend/app/routes/) or temporarily re-enable the
OpenAPI URL locally. All routes are mounted under `/api`.

Health check: `GET /api/health` returns 200 when the DB is reachable.

---

## Codebase tour

### Backend (`backend/app/`)

| Path | Responsibility |
|---|---|
| `main.py` | App factory; wires CORS, the rate limiter, and every router under `/api`. |
| `settings.py` | Pydantic-settings config from the repo-root `.env`. |
| `routes/` | One module per context (auth, soldiers, hierarchy, assignments, constraints, exemptions, exemption_requests, duty_config, scoring, score_adjustments, calendar, me, health). Routes hold Pydantic schemas and call services. |
| `services/` | Business logic, one module per context. The only place routes reach into the domain. |
| `algorithm/` | **Pure** CP-SAT solver (`solver.py`), reserve selection (`reserve.py`), explanation builder (`explain.py`), types/model. No DB or HTTP imports. Has its own `tests/` with fixtures. |
| `auth/` | `password.py` (argon2id), `jwt_tokens.py`, `deps.py` (FastAPI deps like `get_current_user`), `authz.py` (RBAC). |
| `audit/` | `writer.py` — append-only audit row writer (same transaction as the change). |
| `db/` | `models.py` (SQLAlchemy 2.x), `session.py` (`SessionLocal`, `session_scope`), `base.py`. |
| `scripts/` | `bootstrap.py`, `seed.py`, `reset_password.py`. |
| `alembic/versions/` | Migrations `0001`–`0015`, numbered and ordered. |

### Authorization (`auth/authz.py`)
The RBAC core. Read it before touching any management endpoint.
- `Action` — string constants for every guarded action.
- `_DM_ACTIONS` / `_COMMANDER_ACTIONS` — which actions each role may perform.
- `scope_root_ids(session, user)` — the node ids whose subtrees a user governs
  (duty manager → their node; commander → nodes they command; admin → global;
  soldier → none).
- `can(...)` / `authorize(...)` — `authorize` raises 403 unless the user may
  perform the action against the target node's subtree. **Every management
  endpoint must call `authorize`.** Self-reads (own profile/duties) are handled
  at the route level.

### Frontend (`frontend/src/`)

| Path | Responsibility |
|---|---|
| `App.tsx` | Routes. All authenticated routes are wrapped in `ProtectedRoute` and a `ForcedPasswordGate` that redirects to `/change-password` when `mustChangePassword`. |
| `api/` | Typed axios wrappers, one file per context. `client.ts` holds the axios instance (base URL, auth header, refresh handling). |
| `auth/` | `AuthContext.tsx` (current user, login/logout, `mustChangePassword`), `ProtectedRoute.tsx`. |
| `pages/` | One component per screen (Home, MyDuties, MyRequests, Transparency, TeamHierarchy, UnitCalendar, Approvals, DutyConfig, DutyManagement, Profile, Login, ChangePassword). |
| `components/` | Shared UI (Layout/sidebar, HierarchyTree, dialogs, ExemptionsPanel). `Layout.tsx` decides which nav items show per role. |
| `i18n/he.json` | **All** user-facing strings. Hebrew only. RTL is applied app-wide. |

---

## Conventions

From the design doc (§10.5) and current practice:

- **Type-checked end to end** — Pydantic on the backend, TypeScript on the
  frontend. `mypy app` and `tsc --noEmit` must pass.
- **Bounded contexts.** Routes call services; services own the domain logic. The
  `algorithm/` package never imports from `db/` or `routes/`.
- **All user-facing strings live in `i18n/he.json`** (frontend). Backend
  validation errors use stable string keys the frontend maps to Hebrew (see the
  `errors` block in `he.json`).
- **No magic numbers in domain code** — a tunable belongs in `system_settings`,
  or carries a `# why this exact value:` comment.
- **Every state change writes an audit row**, in the same transaction. The audit
  log is append-only at the DB-role level; changes touching it deserve extra
  scrutiny.
- **Every migration is reversible** (`upgrade` + `downgrade`).
- **Files over ~400 lines are a smell** — split by responsibility.
- **Lint/format:** `ruff` (backend), `eslint` + `prettier` (frontend). Frontend
  lint runs with `--max-warnings 0`.

---

## Testing

```bash
# Backend (from backend/) — needs Docker for integration tests
uv run pytest -q                      # everything
uv run pytest tests/unit -q           # fast, no DB
uv run pytest tests/integration -q    # spins up Postgres via testcontainers

# Frontend (from frontend/)
pnpm test                             # vitest unit
pnpm test:e2e                         # playwright e2e
```

- **`tests/unit/`** — pure service/auth/algorithm logic over fakes. No DB.
- **`tests/integration/`** — real FastAPI + real Postgres (testcontainers) + real
  auth. Includes an RBAC matrix test (`test_rbac_matrix.py`) and an audit
  append-only test — keep these green.
- **`backend/app/algorithm/tests/`** — solver correctness against committed JSON
  fixtures (`small_balanced.json`, `density_stress.json`).
- **`frontend/tests/e2e/`** — Playwright flows per feature (login, hierarchy,
  exemptions, duty config, constraints, calendar, assignments…).

CI runs lint + type-check + tests for both sides on every PR — match it locally
before pushing.

---

## Database & migrations

- Migrations are numbered `0001`…`NNNN` and live in
  [`backend/alembic/versions/`](../../backend/alembic/versions/). Each creates one
  table or concern.
- `0001` provisions the `app` role and grants; later migrations grant table-level
  permissions to `app` as they create tables.
- Create one: `uv run alembic revision -m "create X"`, fill `upgrade()` and a
  real `downgrade()`, then `uv run alembic upgrade head`.
- The audit log (`audit_log`) is **INSERT/SELECT only** for the `app` role —
  never write an `UPDATE`/`DELETE` path against it from app code.

To wipe local data: stop the app, `docker-compose down`, delete the
`.docker-data/pg` volume directory, then `docker-compose up -d db` and re-migrate.

---

## How to add a feature

This project is built **slice by slice** from specs and plans under
`docs/superpowers/`. The established loop:

1. **Spec** the feature (`docs/superpowers/specs/`) — the *why* and the shape.
2. **Plan** it (`docs/superpowers/plans/`) — concrete, ordered implementation
   steps. Existing plans are good templates.
3. **Migration** if the data model changes — new numbered Alembic revision, with
   `downgrade`, granting `app` permissions on new tables.
4. **Model** in `db/models.py`.
5. **Service** in `services/` for the logic; keep routes thin.
6. **Route** in `routes/` with Pydantic schemas; call `authorize(...)` for any
   guarded action; write an audit row for any state change.
7. **Frontend**: `api/` wrapper → `pages/`/`components/` → strings in
   `i18n/he.json` → nav entry in `Layout.tsx` if it's a new screen (role-gated).
8. **Tests**: unit (service), integration (route + RBAC + audit), and an e2e flow.
9. **Run the gate**: ruff, mypy, pytest, eslint, tsc, vitest — all green.

See [agents.md](agents.md) for how the superpowers workflow and per-task commit
discipline apply here.
