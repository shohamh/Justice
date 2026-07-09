# Justice — Army Duty Management System

A self-hostable system for assigning duties (**תורנויות**) to soldiers fairly,
with audit-logged workflows and a fairness-aware CP-SAT optimisation core.
Built for a pilot of ~100 soldiers in a single branch.

The UI is **Hebrew-only and right-to-left**; all backend code, identifiers, and
API payloads are in English.

> **Status (current):** v2 is in place. Auth, full data model, hierarchy +
> soldier management, duty types/locations/exemptions/eligibility, personal
> constraints + exemption request approval flows, manual duty assignment with
> per-day overrides, cumulative + normalised scoring, full audit trail. The
> CP-SAT fairness algorithm is **wired to the API** — a duty manager can run it
> against a set of duty shifts, review the proposals, and publish them.
> Recurring shift templates auto-generate empty `duty_shifts` from a weekly
> pattern. Soldiers can post duty swap/cover requests (direct or open board) with
> configurable two-sided manager approval. See [Roadmap](#roadmap).

---

## Documentation map

| Audience | Start here |
|---|---|
| **End users** (admin, duty manager, commander, soldier) | [docs/onboarding/user-guide.md](docs/onboarding/user-guide.md) |
| **Developers** (humans setting up & contributing) | [docs/onboarding/developers.md](docs/onboarding/developers.md) |
| **AI agents** working in this repo | [docs/onboarding/agents.md](docs/onboarding/agents.md) |
| **Full design rationale** | [docs/superpowers/specs/2026-05-27-army-duty-management-design.md](docs/superpowers/specs/2026-05-27-army-duty-management-design.md) |
| **Per-feature implementation plans** | [docs/superpowers/plans/](docs/superpowers/plans/) |

---

## What it does

- **Tracks** soldiers, a four-level hierarchy (team → group → branch → department),
  duty types + eligibility rules, duty locations, exemptions, and personal constraints.
- **Assigns** duties as contiguous blocks `(soldier, duty_type, location, start_date,
  end_date)` with a per-day override layer for replacements and cancellations.
- **Optimises** assignments automatically: the CP-SAT fairness solver is wired to
  an API endpoint — the DM selects a set of duty shifts, runs the algorithm, reviews
  proposals, and publishes them. Assignments are explained ("?למה קיבלתי").
- **Templates** recurring shifts: a DM defines a weekly shift pattern (duty type,
  location, days, required headcount), previews the generated slots, and confirms —
  the algorithm then fills them on each planning run.
- **Swaps**: soldiers post a duty-day they need covered (direct request to a peer, or
  an open board); peers claim it; the effective assignee changes via the override
  layer so scoring follows automatically. A configurable two-sided approval gate is
  enforced when enabled.
- **Keeps effort fair** via a per-soldier *normalised score* (cumulative duty score
  divided by active days), shown on a transparent, peer-comparable scoreboard
  (**שקיפות**).
- **Enforces process**: soldiers submit personal-constraint and exemption requests;
  commanders / duty managers approve or reject them; quotas are enforced.
- **Imports from Excel**: a duty manager uploads an `.xlsx` file and reviews a
  persistent, resumable import session — per-row status (new/update/error/out of
  scope), inline creation of missing duty types or hierarchy nodes, and partial
  confirm (valid rows apply even if some rows are skipped or fixed later). Import
  is scoped to the DM's managed subtree; admins see everything. Parsing is
  pluggable (`backend/app/services/import_parsers/`) so new spreadsheet layouts
  can be supported without touching the review/confirm pipeline.
- **Sub-unit shift quotas**: a single duty shift can require an exact number of
  soldiers from specific hierarchy nodes (e.g. 2 from ענף פוקוס, 3 from ענף
  אלומות) alongside unconstrained slots. The CP-SAT solver enforces these as hard
  constraints, with an optional one-level-up relaxation (manual or automatic) when
  a quota can't be met at the exact node.
- **Audits everything**: every state change is recorded in an append-only audit log.

## Roles at a glance

| Role | Can do |
|---|---|
| **Soldier** | View own duties, score & rank; submit constraint/exemption requests; view the transparency table. |
| **Commander** | Everything a soldier can, plus read & approve requests and grant exemptions **within the subtree they command**. |
| **Duty Manager** | Operational owner of a scope: manage duties, exemptions, constraints, scoring, hierarchy and soldiers **within their assigned node's subtree**. |
| **Admin** | System-level: create soldiers, assign roles, reset passwords, edit hierarchy — **globally**. Deliberately does *not* run day-to-day duty operations. |

Roles compose with hierarchy **scope**. Full matrix and walkthroughs:
[user-guide.md](docs/onboarding/user-guide.md).

---

## Architecture

```
Browser ── React SPA (Vite + TS, RTL, react-i18next, TanStack Query)
   │  HTTPS, JWT bearer in Authorization header; refresh token in HttpOnly cookie
   ▼
FastAPI app (uvicorn)
   ├─ routes/      REST endpoints + Pydantic schemas (all under /api)
   ├─ services/    business logic, one module per bounded context
   ├─ algorithm/   CP-SAT batch solver + reserve + explain (PURE — no DB/HTTP)
   ├─ auth/        argon2id passwords, JWT, central RBAC (authz.py)
   ├─ audit/       append-only audit writer
   └─ db/          SQLAlchemy 2.x models + Alembic migrations
   ▼
Postgres 16  (two DB roles: db_admin for migrations/backup, app for the runtime)
```

**Tech stack:** Python 3.12 · FastAPI · SQLAlchemy 2.x · Alembic · Pydantic v2 ·
OR-Tools CP-SAT · React 18 · Vite · TypeScript · TanStack Query · Tailwind (RTL)
· Postgres 16.

**Key design choices** (see the design doc for the why):

- Monolith + workers, no message queue. CP-SAT solves the pilot-scale problem
  synchronously in seconds.
- `algorithm/` is a **pure library**: plain data in, plain data out, no imports
  from `db/` or `routes/`. Unit-testable without a database.
- All tunable behaviour belongs in a `system_settings` table, not in code. Env
  vars cover deployment-level concerns only (DB URL, JWT secret, log level).
- Two Postgres roles: `app` (runtime, restricted) and `db_admin` (migrations,
  backups). The audit log is append-only for the `app` role.

---

## Quick start (local dev)

### Option A — Full Docker (recommended)

Prerequisites: **Docker**.

```bash
# 1. Configuration
cp .env.example .env            # review values; defaults work for Docker

# 2. Start everything (db + backend + frontend)
docker-compose up --build

# 3. Create the first admin (run once after the first `up`)
docker-compose exec backend uv run python -m app.scripts.bootstrap
```

Open <http://localhost:5173> and log in with the bootstrap admin
(`BOOTSTRAP_ADMIN_PERSONAL_NUMBER` / `BOOTSTRAP_ADMIN_PASSWORD` from `.env`).

> **`COOKIE_SECURE`:** keep this `false` unless the app is served over real HTTPS.
> Browsers silently drop the `refresh_token` cookie over plain HTTP when it's `true`,
> which manifests as an unexplained logout on page refresh. This also applies to
> deployments fronted by a TLS-terminating proxy (e.g. a Tailscale funnel) — the
> backend process itself still sees a plain-HTTP request, so `COOKIE_SECURE` must
> stay `false` there too.

The `backend` service automatically runs `alembic upgrade head` before starting,
so migrations are always applied on container start.

> **Rebuilding the frontend:** Vite bakes `VITE_API_BASE` into the static bundle
> at build time. If you change that value in `.env`, run
> `docker-compose up --build frontend` to rebuild.

### Option B — Native dev with hot reload (recommended for Windows)

Prerequisites: **Docker**, **Python 3.12 + [uv](https://docs.astral.sh/uv/)**,
**Node 20 + [pnpm](https://pnpm.io/) 9**.

```powershell
.\dev.ps1        # backend + frontend + Telegram bot
.\dev.ps1 -NoBot # skip the bot
```

That's it. The script handles everything in one terminal window:
- Keeps Postgres in Docker, runs backend/frontend/bot natively
- Stops any running Docker app containers (frees ports 8000 / 5173)
- Waits for DB health, runs Alembic migrations automatically
- Streams all logs with colored `[backend]` / `[frontend]` / `[bot]` prefixes
- **Ctrl+C** stops all services cleanly

Open <http://localhost:5173>.

> **Why not `docker compose up`?** Docker Desktop on Windows doesn't reliably
> forward filesystem events into containers, so Vite HMR and uvicorn `--reload`
> miss file saves. Running natively fixes this entirely.

### Seed demo data (optional)

To explore the system with a realistic hierarchy, soldiers of every role, duty
types, exemptions, shifts, and a month of assignments:

```bash
# Docker
docker-compose exec backend uv run python -m app.scripts.seed

# On-host
cd backend && uv run python -m app.scripts.seed
```

The seed creates a known **admin** `1000001` with password `1234567890`
(`must_change_password=False`). Personal numbers follow a pattern — see
[user-guide.md](docs/onboarding/user-guide.md#demo-accounts) for the full
account list. **Seed data is for development only.**

---

## Common commands

```powershell
# Dev stack (recommended — runs natively for reliable hot reload)
.\dev.ps1        # backend + frontend + bot, all in one terminal
.\dev.ps1 -NoBot # skip the bot
```

```bash
# Docker Compose (DB only, or full-Docker option)
docker-compose up --build            # start everything in Docker
docker-compose up -d db              # start db only (used by dev.ps1)
docker-compose exec backend <cmd>    # run a command inside the backend container
docker-compose down                  # stop all services

# Backend (run from backend/ — or via `docker-compose exec backend`)
uv run uvicorn app.main:app --reload --port 8000   # dev server (hot reload)
uv run alembic upgrade head                         # apply migrations
uv run alembic revision -m "describe change"        # new migration
uv run pytest -q                                    # all tests (needs Docker for testcontainers)
uv run ruff check app tests                         # lint
uv run ruff format app tests                        # format
uv run mypy app                                     # type check
uv run python -m app.scripts.bootstrap              # create first admin (idempotent)
uv run python -m app.scripts.seed                   # seed demo data
uv run python -m app.scripts.reset_password <pn>    # reset a password (prints a temp one)

# Frontend (run from frontend/)
pnpm dev            # dev server on :5173
pnpm build          # type-check + production build
pnpm lint           # eslint (zero warnings)
pnpm test           # vitest unit tests
pnpm test:e2e       # playwright end-to-end tests
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs ruff + mypy +
pytest for the backend and lint + tsc + vitest + build for the frontend on every
PR.

---

## Repo layout

```
justice/
├── README.md                ← you are here
├── docker-compose.yml       ← Postgres for local dev (app/frontend run on host)
├── .env.example             ← copy to .env
├── docs/
│   ├── onboarding/          ← user, developer & agent guides (start here)
│   └── superpowers/
│       ├── specs/           ← design docs (the "why")
│       └── plans/           ← per-slice implementation plans
├── backend/
│   ├── app/
│   │   ├── main.py          ← FastAPI app factory + router wiring
│   │   ├── routes/          ← REST endpoints (one module per context)
│   │   ├── services/        ← business logic
│   │   ├── algorithm/       ← pure CP-SAT solver + tests
│   │   ├── auth/            ← password, JWT, authz (RBAC)
│   │   ├── audit/           ← append-only audit writer
│   │   ├── db/              ← models + session
│   │   ├── scripts/         ← bootstrap, seed, reset_password
│   │   └── settings.py      ← env-var config
│   ├── alembic/versions/    ← migrations
│   └── tests/{unit,integration}
└── frontend/
    ├── src/{api,pages,components,auth,i18n}
    └── tests/e2e            ← playwright specs
```

---

## Installing Python dependencies offline

If you need to install the backend on a machine with no internet access, use uv's
wheel-download workflow.

**Step 1 — on an internet-connected machine** (same OS / Python version as the target):

```powershell
cd backend
uv export --frozen --no-dev -o requirements-vendor.txt
uv pip download -r requirements-vendor.txt --dest vendor/
```

This writes every required wheel into `backend/vendor/`. Zip it up and copy the
whole `backend/` directory (including `uv.lock` and `vendor/`) to the offline machine.

**Step 2 — on the offline machine**:

```powershell
cd backend
uv venv
uv pip install --no-index --find-links vendor/ -r requirements-vendor.txt
```

`vendor/` is in `.gitignore` — don't commit the wheels.

---

## Roadmap

- **v1 — Foundation** ✅: data model, auth, manual workflows, scoring, audit.
- **v1.5 — Algorithm** ✅: CP-SAT solver wired to the API; DM review UI;
  assignment explanations ("?למה קיבלתי"); hierarchy-distance reserve-soldier
  selection; first-class `duty_shifts` entity; soldier eligibility requirements on
  duty types.
- **v2 — Recurring templates + swaps** ✅: weekly shift templates with
  DM-triggered idempotent generation; duty swap/cover system (direct request + open
  board) with configurable two-sided manager approval.
- **v2.1 — Excel import + sub-unit quotas** ✅: persistent, resumable import
  sessions with pluggable parsers, DM-scoped row resolution, inline fix-and-retry
  for missing entities, and partial confirm; per-shift exact sub-unit soldier
  quotas enforced by the solver with one-level-up relaxation.
- **Next**: production deployment artefacts (Caddy, TLS, prod compose);
  notifications (SMS/push) for swap offers and approval decisions; greedy online
  assignment for ad-hoc single duties; no-show / punishment-duty mechanic;
  longitudinal fairness dashboard.

See [§9 of the design doc](docs/superpowers/specs/2026-05-27-army-duty-management-design.md)
for the original phasing (note: v2 scope was re-scoped — see
[the v2 brainstorm spec](docs/superpowers/specs/2026-05-30-v2-rescope-brainstorm.md)).

## Known gaps vs. the design doc

The design doc describes the full target system. Today's deviations worth knowing:

- `docker-compose.yml` provisions **only Postgres**; the app and frontend run on
  the host in dev. There is no Caddy/TLS or production compose file checked in yet.
- FastAPI's `/api/docs` and `/api/openapi.json` are currently **disabled**
  (`docs_url=None`) rather than gated behind admin.
- The **open swap board** ranks offers by duty date only; full hierarchy-distance +
  match-quality ranking is a planned improvement.
- The **swap create UI** asks for an assignment ID directly — a duty-day picker
  showing upcoming published assignments is planned.
