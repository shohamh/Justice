# Slice 1: Foundation & First Login — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a self-hostable Python + React monorepo where a user can log in with a personal number + password, see a Hebrew RTL placeholder home page, and have the action audited — with all the infrastructure (DB schema, migrations, settings, audit log, JWT auth, RBAC, bootstrap, CI, Docker) needed by every later slice already in place.

**Architecture:** FastAPI backend with SQLAlchemy 2.x + Alembic over Postgres 16; React + Vite + TypeScript frontend with react-i18next + tailwindcss-rtl; argon2id passwords + JWT (short access token + HttpOnly refresh cookie); audit log as an append-only Postgres table with a separate `db_admin` role that owns it and an `app` role with `INSERT, SELECT` only; system settings as a single JSONB-keyed table; one `docker-compose.yml` brings the stack up locally.

**Tech Stack:** Python 3.12, FastAPI 0.110+, SQLAlchemy 2.x, Alembic, Pydantic v2, argon2-cffi, python-jose for JWT, slowapi (rate limit), pytest + testcontainers-python, Postgres 16, React 18, Vite 5, TypeScript 5, TanStack Query, react-i18next, tailwindcss + tailwindcss-rtl, axios, Vitest, Playwright, Docker, GitHub Actions.

---

## Spec coverage

This slice corresponds to Sections 3 (architecture), 4.1 (audit_log, system_settings, soldiers tables only), 5.3 (auth implementation), 8.2 (security mitigations relevant to login), and 10.1-10.3 (repo layout, testing, CI) of [the design doc](../specs/2026-05-27-army-duty-management-design.md). Hierarchy, exemptions, constraints, duties, scoring, and the algorithm are explicitly **out** of this slice — they ship in slices 2-5.

## File structure produced by this slice

```
justice/
├── .gitignore
├── .env.example
├── README.md
├── docker-compose.yml
├── .github/workflows/ci.yml
│
├── backend/
│   ├── pyproject.toml
│   ├── ruff.toml
│   ├── mypy.ini
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       ├── 0001_create_app_and_admin_roles.py
│   │       ├── 0002_create_audit_log.py
│   │       ├── 0003_create_system_settings.py
│   │       └── 0004_create_soldiers.py
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── settings.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── session.py
│   │   │   └── models.py
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── password.py
│   │   │   ├── jwt_tokens.py
│   │   │   └── deps.py
│   │   ├── audit/
│   │   │   ├── __init__.py
│   │   │   └── writer.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   └── settings_loader.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   └── health.py
│   │   ├── i18n/
│   │   │   └── he.json
│   │   └── scripts/
│   │       └── bootstrap.py
│   └── tests/
│       ├── conftest.py
│       ├── unit/
│       │   ├── test_password.py
│       │   ├── test_jwt_tokens.py
│       │   └── test_settings_loader.py
│       └── integration/
│           ├── test_health.py
│           ├── test_login.py
│           └── test_audit_append_only.py
│
└── frontend/
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    ├── tailwind.config.cjs
    ├── postcss.config.cjs
    ├── index.html
    ├── Dockerfile
    ├── .dockerignore
    ├── src/
    │   ├── main.tsx
    │   ├── App.tsx
    │   ├── api/
    │   │   ├── client.ts
    │   │   └── auth.ts
    │   ├── auth/
    │   │   ├── AuthContext.tsx
    │   │   └── ProtectedRoute.tsx
    │   ├── pages/
    │   │   ├── LoginPage.tsx
    │   │   └── HomePage.tsx
    │   ├── components/
    │   │   └── Layout.tsx
    │   ├── i18n/
    │   │   ├── index.ts
    │   │   └── he.json
    │   └── styles/
    │       └── globals.css
    └── tests/
        └── e2e/
            └── login.spec.ts
```

**File responsibilities:**

- `backend/app/db/models.py` — SQLAlchemy ORM models for `Soldier`, `AuditLog`, `SystemSetting`. Pure model definitions, no business logic.
- `backend/app/db/session.py` — engine + session factory; one place to configure DB connection.
- `backend/app/auth/password.py` — `hash_password()` + `verify_password()` using argon2id. No DB, no I/O.
- `backend/app/auth/jwt_tokens.py` — `issue_access()`, `issue_refresh()`, `decode()`. Pure functions over a secret.
- `backend/app/auth/deps.py` — FastAPI dependency `get_current_user()` that decodes the access token and loads the soldier; later slices add `require(action, target)`.
- `backend/app/audit/writer.py` — `write_audit(session, actor_id, action, ...)`. Runs inside the caller's session; never opens its own.
- `backend/app/services/settings_loader.py` — `get_setting(session, key)` + `set_setting(session, key, value, actor_id)`. Writes audit on update.
- `backend/app/routes/auth.py` — `/api/auth/login`, `/api/auth/refresh`, `/api/auth/logout` endpoints.
- `backend/app/routes/health.py` — `/api/health` (200 if DB reachable).
- `backend/app/scripts/bootstrap.py` — first-boot script: creates the first admin from env vars, then refuses to run again if any admin exists.
- `frontend/src/api/client.ts` — axios instance with bearer-token interceptor + refresh-on-401 logic.
- `frontend/src/auth/AuthContext.tsx` — React context for current user + login/logout.
- `frontend/src/pages/LoginPage.tsx` — login form.
- `frontend/src/pages/HomePage.tsx` — placeholder "ראשי" page; sidebar shell.

---

## Conventions used in this plan

- All shell commands run from the repo root unless stated otherwise.
- Python commands assume `uv` is installed (https://github.com/astral-sh/uv). If you prefer `poetry`, swap `uv pip install` → `poetry add`, `uv run` → `poetry run`.
- Frontend commands use `pnpm`. Install pnpm globally first: `npm i -g pnpm`.
- "Run X. Expected: Y." — actually run it and verify the output matches before continuing.
- Commit after every passing test. Commits are intentionally small.

---

## Phase A — Repo and infrastructure scaffold

### Task 1: Initialise git and write the .gitignore

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `.env.example`

- [ ] **Step 1: Initialise the repo**

Run: `git init`
Expected: `Initialized empty Git repository in C:/Users/Shoham/workspace/justice/.git/`

- [ ] **Step 2: Create `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.uv-cache/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Node
node_modules/
dist/
.vite/

# Editor / OS
.DS_Store
Thumbs.db
.idea/
.vscode/

# Secrets / env
.env
.env.local
*.pem
*.key

# Postgres data volume (when running compose locally)
.docker-data/
```

- [ ] **Step 3: Create `.env.example`**

```dotenv
# Backend
DATABASE_URL=postgresql+psycopg://app:app_pw@db:5432/cod2
DB_ADMIN_URL=postgresql+psycopg://db_admin:db_admin_pw@db:5432/cod2
JWT_SECRET=change-me-in-prod-this-is-only-a-dev-default-with-32-bytes
JWT_ALGORITHM=HS256
ACCESS_TOKEN_MINUTES=15
REFRESH_TOKEN_DAYS=30
ALLOWED_ORIGINS=http://localhost:5173
LOG_LEVEL=INFO
LOGIN_RATE_LIMIT=5/5minutes

# First-boot admin (bootstrap.py reads these once; rotate after first login)
BOOTSTRAP_ADMIN_PERSONAL_NUMBER=1000001
BOOTSTRAP_ADMIN_FULL_NAME=Initial Admin
BOOTSTRAP_ADMIN_PASSWORD=ChangeMeOnFirstLogin!

# Frontend
VITE_API_BASE=http://localhost:8000/api
```

- [ ] **Step 4: Create `README.md`**

```markdown
# Justice — Army Duty Management System

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
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore README.md .env.example
git commit -m "chore: initialise repo with gitignore, readme, env example"
```

---

### Task 2: docker-compose for local Postgres

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Create `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: db_admin
      POSTGRES_PASSWORD: db_admin_pw
      POSTGRES_DB: cod2
    ports:
      - "5432:5432"
    volumes:
      - ./.docker-data/pg:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U db_admin -d cod2"]
      interval: 5s
      timeout: 5s
      retries: 10
```

> The full prod compose (with `app` and `caddy` services) ships in slice 7. This dev one runs only Postgres so we can iterate the backend with hot reload locally.

- [ ] **Step 2: Bring up the DB and verify**

Run: `docker-compose up -d db`
Wait ~10s.
Run: `docker-compose exec db pg_isready -U db_admin -d cod2`
Expected: `/var/run/postgresql:5432 - accepting connections`

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "chore: add docker-compose for local postgres"
```

---

### Task 3: Backend Python project skeleton

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/ruff.toml`
- Create: `backend/mypy.ini`
- Create: `backend/app/__init__.py`

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "justice-backend"
version = "0.1.0"
description = "Army duty management backend"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "sqlalchemy>=2.0.27",
  "alembic>=1.13",
  "psycopg[binary]>=3.1",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "argon2-cffi>=23.1",
  "python-jose[cryptography]>=3.3",
  "slowapi>=0.1.9",
  "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
  "testcontainers[postgres]>=4.0",
  "hypothesis>=6.99",
  "ruff>=0.3",
  "mypy>=1.9",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra -q"
asyncio_mode = "auto"
```

- [ ] **Step 2: Create `backend/ruff.toml`**

```toml
line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "I", "B", "UP", "N", "ASYNC", "SIM"]
ignore = ["E501"]  # line length handled by formatter
```

- [ ] **Step 3: Create `backend/mypy.ini`**

```ini
[mypy]
python_version = 3.12
strict = true
plugins = pydantic.mypy
warn_unused_ignores = true

[mypy-tests.*]
disallow_untyped_decorators = false
```

- [ ] **Step 4: Create `backend/app/__init__.py`** (empty file).

- [ ] **Step 5: Install deps**

Run: `cd backend && uv sync --extra dev && cd ..`
Expected: `Resolved N packages in ...` then `Installed N packages in ...` with no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/ruff.toml backend/mypy.ini backend/app/__init__.py backend/uv.lock
git commit -m "chore(backend): python project skeleton with deps"
```

---

### Task 4: Backend settings module

Centralised env-var loading so no module reads `os.environ` directly.

**Files:**
- Create: `backend/app/settings.py`

- [ ] **Step 1: Create `backend/app/settings.py`**

```python
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    db_admin_url: str = Field(alias="DB_ADMIN_URL")
    jwt_secret: str = Field(alias="JWT_SECRET", min_length=32)
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_minutes: int = Field(default=15, alias="ACCESS_TOKEN_MINUTES")
    refresh_token_days: int = Field(default=30, alias="REFRESH_TOKEN_DAYS")
    allowed_origins: str = Field(default="http://localhost:5173", alias="ALLOWED_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    login_rate_limit: str = Field(default="5/5minutes", alias="LOGIN_RATE_LIMIT")

    bootstrap_admin_personal_number: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_PERSONAL_NUMBER")
    bootstrap_admin_full_name: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_FULL_NAME")
    bootstrap_admin_password: str | None = Field(default=None, alias="BOOTSTRAP_ADMIN_PASSWORD")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/settings.py
git commit -m "feat(backend): centralized settings via pydantic-settings"
```

---

## Phase B — Database, migrations, audit

### Task 5: Alembic setup with two roles

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`

- [ ] **Step 1: Initialise Alembic in-place**

Run: `cd backend && uv run alembic init -t async alembic && cd ..`
Expected: directory `backend/alembic/` is created with `env.py`, `script.py.mako`, `versions/`.

> We are not actually using async migrations here; we use the async layout because it produces a cleaner `env.py`. We'll switch to sync engine in the next step.

- [ ] **Step 2: Replace `backend/alembic.ini`'s `sqlalchemy.url` line**

Find: `sqlalchemy.url = driver://user:pass@localhost/dbname`
Replace with: `sqlalchemy.url =` (empty — we set it programmatically in env.py)

- [ ] **Step 3: Replace `backend/alembic/env.py` with this content**

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.base import Base
from app.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.db_admin_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Create `backend/app/db/__init__.py`** (empty file).

- [ ] **Step 5: Create `backend/app/db/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass


class Base(MappedAsDataclass, DeclarativeBase):
    """Project-wide declarative base."""
```

- [ ] **Step 6: Create `backend/app/db/session.py`**

```python
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import get_settings


def _make_engine_factory():
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return engine, factory


_engine, SessionLocal = _make_engine_factory()


def get_session() -> Iterator[Session]:
    """FastAPI dependency — yields a session and closes it on request completion."""
    with SessionLocal() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standalone context manager for scripts and tests outside FastAPI."""
    with SessionLocal() as session:
        yield session
```

- [ ] **Step 7: Commit**

```bash
git add backend/alembic.ini backend/alembic/env.py backend/alembic/script.py.mako backend/app/db/
git commit -m "chore(backend): alembic + sqlalchemy base + session factory"
```

---

### Task 6: Create the `app` and `db_admin` Postgres roles

This is migration 0001. It runs *as* `db_admin` (per `DB_ADMIN_URL`) and creates the lower-privileged `app` role that the running application will use.

**Files:**
- Create: `backend/alembic/versions/0001_create_app_and_admin_roles.py`

- [ ] **Step 1: Create `backend/alembic/versions/0001_create_app_and_admin_roles.py`**

```python
"""create app role

Revision ID: 0001
Revises:
Create Date: 2026-05-27

This migration runs as db_admin. It creates the lower-privileged 'app' role
that the FastAPI process authenticates as. Permissions on individual tables
are granted by the migrations that create those tables.
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app') THEN
                CREATE ROLE app LOGIN PASSWORD 'app_pw';
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT CONNECT ON DATABASE cod2 TO app;")
    op.execute("GRANT USAGE ON SCHEMA public TO app;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app;")


def downgrade() -> None:
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM app;")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM app;")
    op.execute("REVOKE USAGE ON SCHEMA public FROM app;")
    op.execute("REVOKE CONNECT ON DATABASE cod2 FROM app;")
    op.execute("DROP ROLE IF EXISTS app;")
```

- [ ] **Step 2: Apply**

Run: `cd backend && uv run alembic upgrade head && cd ..`
Expected: `INFO  [alembic.runtime.migration] Running upgrade  -> 0001, create app role`

- [ ] **Step 3: Verify the role exists**

Run: `docker-compose exec db psql -U db_admin -d cod2 -c "\du app"`
Expected: a row showing `app` with `LOGIN` attributes.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0001_create_app_and_admin_roles.py
git commit -m "feat(db): create app role with default privileges"
```

---

### Task 7: Migration 0002 — audit_log (append-only)

Creates the audit table and grants `app` only `INSERT, SELECT` — not `UPDATE` or `DELETE`. This is the tamper-evidence guarantee.

**Files:**
- Create: `backend/alembic/versions/0002_create_audit_log.py`

- [ ] **Step 1: Create the migration**

```python
"""create audit_log

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("actor_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("after", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("context", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    # Append-only: app can only INSERT and SELECT.
    op.execute("REVOKE ALL ON TABLE audit_log FROM app;")
    op.execute("GRANT SELECT, INSERT ON TABLE audit_log TO app;")


def downgrade() -> None:
    op.drop_table("audit_log")
```

> `gen_random_uuid()` needs the `pgcrypto` extension. It's bundled with Postgres 16 alpine.

- [ ] **Step 2: Apply**

Run: `cd backend && uv run alembic upgrade head && cd ..`
Expected: `Running upgrade 0001 -> 0002, create audit_log`

- [ ] **Step 3: Verify append-only privileges**

Run: `docker-compose exec db psql -U db_admin -d cod2 -c "SELECT privilege_type FROM information_schema.role_table_grants WHERE grantee='app' AND table_name='audit_log' ORDER BY 1;"`
Expected: two rows, `INSERT` and `SELECT`. No `UPDATE` or `DELETE`.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0002_create_audit_log.py
git commit -m "feat(db): audit_log table, append-only for app role"
```

---

### Task 8: Migration 0003 — system_settings

**Files:**
- Create: `backend/alembic/versions/0003_create_system_settings.py`

- [ ] **Step 1: Create the migration**

```python
"""create system_settings

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-27
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


DEFAULTS: dict[str, object] = {
    "auth.session_minutes": 15,
    "auth.refresh_days": 30,
    "auth.login_rate_limit_per_5m": 5,
}


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    # Seed auth-relevant defaults; later slices seed their own keys in their migrations.
    rows = [{"key": k, "value": json.dumps(v)} for k, v in DEFAULTS.items()]
    if rows:
        op.execute(sa.text("INSERT INTO system_settings (key, value) VALUES " + ", ".join(f"('{r['key']}', '{r['value']}'::jsonb)" for r in rows)))


def downgrade() -> None:
    op.drop_table("system_settings")
```

- [ ] **Step 2: Apply**

Run: `cd backend && uv run alembic upgrade head && cd ..`
Expected: `Running upgrade 0002 -> 0003, create system_settings`

- [ ] **Step 3: Verify seed rows**

Run: `docker-compose exec db psql -U db_admin -d cod2 -c "SELECT key, value FROM system_settings ORDER BY key;"`
Expected: three rows for `auth.login_rate_limit_per_5m`, `auth.refresh_days`, `auth.session_minutes`.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0003_create_system_settings.py
git commit -m "feat(db): system_settings table with auth defaults seeded"
```

---

### Task 9: Migration 0004 — soldiers

This is the only domain table this slice creates. Hierarchy nodes, duties, exemptions, constraints all come in later slices and reference `soldiers.id`.

**Files:**
- Create: `backend/alembic/versions/0004_create_soldiers.py`

- [ ] **Step 1: Create the migration**

```python
"""create soldiers

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


ROLE_ENUM = sa.Enum("soldier", "commander", "duty_manager", "admin", name="soldier_role")


def upgrade() -> None:
    ROLE_ENUM.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "soldiers",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("personal_number", sa.Text(), nullable=False, unique=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", ROLE_ENUM, nullable=False, server_default="soldier"),
        sa.Column("hierarchy_node_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),  # FK added in slice 2
        sa.Column("enrolled_at", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("left_at", sa.Date(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_soldiers_personal_number", "soldiers", ["personal_number"], unique=True)
    op.create_index("ix_soldiers_role", "soldiers", ["role"])
    op.create_index("ix_soldiers_active", "soldiers", ["left_at"])


def downgrade() -> None:
    op.drop_table("soldiers")
    ROLE_ENUM.drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 2: Apply**

Run: `cd backend && uv run alembic upgrade head && cd ..`
Expected: `Running upgrade 0003 -> 0004, create soldiers`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0004_create_soldiers.py
git commit -m "feat(db): soldiers table with role enum"
```

---

### Task 10: ORM models (Soldier, AuditLog, SystemSetting)

**Files:**
- Create: `backend/app/db/models.py`

- [ ] **Step 1: Create `backend/app/db/models.py`**

```python
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Enum, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Soldier(Base):
    __tablename__ = "soldiers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    personal_number: Mapped[str] = mapped_column(Text, unique=True)
    full_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Enum("soldier", "commander", "duty_manager", "admin", name="soldier_role"), server_default="soldier", default="soldier")
    hierarchy_node_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    enrolled_at: Mapped[date] = mapped_column(Date, server_default=text("CURRENT_DATE"), default=None)
    left_at: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
```

- [ ] **Step 2: Verify the import graph**

Run: `cd backend && uv run python -c "from app.db.models import Soldier, AuditLog, SystemSetting; print('ok')" && cd ..`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat(db): ORM models for soldier, audit log, system settings"
```

---

### Task 11: Password hashing (TDD)

**Files:**
- Create: `backend/app/auth/__init__.py`
- Create: `backend/app/auth/password.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/unit/__init__.py`
- Create: `backend/tests/unit/test_password.py`

- [ ] **Step 1: Create `backend/app/auth/__init__.py`** (empty file).

- [ ] **Step 2: Create `backend/tests/__init__.py`** (empty file).

- [ ] **Step 3: Create `backend/tests/unit/__init__.py`** (empty file).

- [ ] **Step 4: Create `backend/tests/conftest.py`** with a no-op for now**

```python
# tests/conftest.py
# DB and HTTP fixtures will be added in later tasks. This file exists so
# pytest treats `tests/` as the test root cleanly.
```

- [ ] **Step 5: Create the failing test `backend/tests/unit/test_password.py`**

```python
import pytest

from app.auth.password import hash_password, verify_password


def test_hash_password_returns_string_with_argon2_prefix():
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")


def test_verify_password_accepts_correct_password():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_password_rejects_wrong_password():
    h = hash_password("correct horse battery staple")
    assert verify_password("wrong", h) is False


def test_hash_is_salted_so_two_hashes_of_same_password_differ():
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    assert verify_password("same", a)
    assert verify_password("same", b)


def test_verify_returns_false_on_malformed_hash():
    assert verify_password("anything", "not-a-real-hash") is False
```

- [ ] **Step 6: Run the test — expect FAIL**

Run: `cd backend && uv run pytest tests/unit/test_password.py -v && cd ..`
Expected: ImportError / ModuleNotFoundError on `app.auth.password`.

- [ ] **Step 7: Create `backend/app/auth/password.py`**

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHash

# Argon2id is the default; tuned to ~100ms on commodity hardware.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False
```

- [ ] **Step 8: Run the test — expect PASS**

Run: `cd backend && uv run pytest tests/unit/test_password.py -v && cd ..`
Expected: 5 passed.

- [ ] **Step 9: Commit**

```bash
git add backend/app/auth/__init__.py backend/app/auth/password.py backend/tests/
git commit -m "feat(auth): argon2id password hashing with tests"
```

---

### Task 12: JWT tokens (TDD)

**Files:**
- Create: `backend/app/auth/jwt_tokens.py`
- Create: `backend/tests/unit/test_jwt_tokens.py`

- [ ] **Step 1: Create the failing test**

```python
# backend/tests/unit/test_jwt_tokens.py
import time
import uuid

import pytest

from app.auth.jwt_tokens import (
    InvalidToken,
    decode_token,
    issue_access_token,
    issue_refresh_token,
)


def test_access_token_round_trip():
    user_id = uuid.uuid4()
    token = issue_access_token(user_id=user_id, role="soldier")
    payload = decode_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "soldier"
    assert payload["type"] == "access"


def test_refresh_token_has_different_type_claim():
    token = issue_refresh_token(user_id=uuid.uuid4())
    payload = decode_token(token)
    assert payload["type"] == "refresh"


def test_invalid_token_raises():
    with pytest.raises(InvalidToken):
        decode_token("garbage.token.value")


def test_expired_token_raises(monkeypatch):
    # Issue with a 0-second lifetime
    user_id = uuid.uuid4()
    token = issue_access_token(user_id=user_id, role="soldier", lifetime_seconds=0)
    time.sleep(1)
    with pytest.raises(InvalidToken):
        decode_token(token)


def test_tampered_token_raises():
    token = issue_access_token(user_id=uuid.uuid4(), role="soldier")
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(InvalidToken):
        decode_token(tampered)
```

- [ ] **Step 2: Run the test — expect FAIL** (module not found).

Run: `cd backend && uv run pytest tests/unit/test_jwt_tokens.py -v && cd ..`
Expected: ImportError.

- [ ] **Step 3: Create `backend/app/auth/jwt_tokens.py`**

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from app.settings import get_settings


class InvalidToken(Exception):
    """Raised when a token cannot be decoded or has expired."""


def _now() -> datetime:
    return datetime.now(tz=UTC)


def issue_access_token(*, user_id: uuid.UUID, role: str, lifetime_seconds: int | None = None) -> str:
    settings = get_settings()
    if lifetime_seconds is None:
        lifetime_seconds = settings.access_token_minutes * 60
    exp = _now() + timedelta(seconds=lifetime_seconds)
    payload = {"sub": str(user_id), "role": role, "type": "access", "exp": int(exp.timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def issue_refresh_token(*, user_id: uuid.UUID, lifetime_seconds: int | None = None) -> str:
    settings = get_settings()
    if lifetime_seconds is None:
        lifetime_seconds = settings.refresh_token_days * 24 * 3600
    exp = _now() + timedelta(seconds=lifetime_seconds)
    payload = {"sub": str(user_id), "type": "refresh", "exp": int(exp.timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidToken(str(exc)) from exc
```

- [ ] **Step 4: Run the test — expect PASS**

Run: `cd backend && uv run pytest tests/unit/test_jwt_tokens.py -v && cd ..`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth/jwt_tokens.py backend/tests/unit/test_jwt_tokens.py
git commit -m "feat(auth): JWT issue/decode with tests"
```

---

### Task 13: Audit writer

**Files:**
- Create: `backend/app/audit/__init__.py`
- Create: `backend/app/audit/writer.py`

- [ ] **Step 1: Create `backend/app/audit/__init__.py`** (empty file).

- [ ] **Step 2: Create `backend/app/audit/writer.py`**

```python
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def write_audit(
    session: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> AuditLog:
    """Append a row to the audit log.

    Must be called from within an existing session/transaction so the audit
    write and the underlying mutation succeed or fail atomically. Never opens
    its own session.
    """
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        context=context,
    )
    session.add(entry)
    return entry
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/audit/__init__.py backend/app/audit/writer.py
git commit -m "feat(audit): write_audit() helper writing into caller's session"
```

---

### Task 14: Integration test — `audit_log` is append-only at the DB level

This is the critical property test for the tamper-evidence guarantee.

**Files:**
- Create: `backend/tests/integration/__init__.py`
- Create: `backend/tests/integration/test_audit_append_only.py`

- [ ] **Step 1: Create `backend/tests/integration/__init__.py`** (empty file).

- [ ] **Step 2: Extend `backend/tests/conftest.py` with DB fixtures**

```python
# tests/conftest.py
import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_admin_url(pg_container: PostgresContainer) -> str:
    """Superuser URL from testcontainers, normalised to the psycopg3 driver."""
    url = make_url(pg_container.get_connection_url()).set(drivername="postgresql+psycopg")
    return str(url)


@pytest.fixture(scope="session", autouse=True)
def _apply_schema(db_admin_url: str) -> None:
    """Run migrations against the throwaway container at session start.

    Also sets env vars BEFORE any app module is imported, so settings cache picks
    them up. Pumps the login rate limit high so the multi-login test suite isn't
    artificially throttled.
    """
    os.environ["DATABASE_URL"] = db_admin_url
    os.environ["DB_ADMIN_URL"] = db_admin_url
    os.environ["JWT_SECRET"] = "test-secret-32-bytes-of-padding-_-x"
    os.environ["LOGIN_RATE_LIMIT"] = "10000/minute"

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    command.upgrade(cfg, "head")


@pytest.fixture()
def admin_engine(db_admin_url: str):
    return create_engine(db_admin_url, future=True)


@pytest.fixture()
def admin_session(admin_engine) -> Iterator[Session]:
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as s:
        yield s


@pytest.fixture()
def app_engine(db_admin_url: str):
    """Engine using the unprivileged 'app' role — exposes RBAC errors at the DB layer."""
    app_url = make_url(db_admin_url).set(username="app", password="app_pw")
    return create_engine(str(app_url), future=True)


@pytest.fixture()
def app_session(app_engine) -> Iterator[Session]:
    SessionLocal = sessionmaker(bind=app_engine, expire_on_commit=False)
    with SessionLocal() as s:
        yield s
```

- [ ] **Step 3: Create the test `backend/tests/integration/test_audit_append_only.py`**

```python
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.audit.writer import write_audit


def test_app_role_can_insert_into_audit_log(app_session):
    write_audit(app_session, actor_id=None, action="test.action", entity_type="test", entity_id=uuid.uuid4(), after={"hello": "world"})
    app_session.commit()
    row = app_session.execute(text("SELECT action FROM audit_log ORDER BY created_at DESC LIMIT 1")).first()
    assert row is not None
    assert row[0] == "test.action"


def test_app_role_cannot_update_audit_log(app_session):
    write_audit(app_session, actor_id=None, action="will.be.attacked", entity_type="test", entity_id=uuid.uuid4())
    app_session.commit()
    with pytest.raises(ProgrammingError) as exc:
        app_session.execute(text("UPDATE audit_log SET action='tampered' WHERE action='will.be.attacked'"))
        app_session.commit()
    assert "permission denied" in str(exc.value).lower()


def test_app_role_cannot_delete_from_audit_log(app_session):
    write_audit(app_session, actor_id=None, action="will.be.deleted", entity_type="test", entity_id=uuid.uuid4())
    app_session.commit()
    with pytest.raises(ProgrammingError) as exc:
        app_session.execute(text("DELETE FROM audit_log WHERE action='will.be.deleted'"))
        app_session.commit()
    assert "permission denied" in str(exc.value).lower()
```

- [ ] **Step 4: Run the audit append-only test — expect PASS**

Run: `cd backend && uv run pytest tests/integration/test_audit_append_only.py -v && cd ..`
Expected: 3 passed.

> If the `app` role inherits superuser privileges in the testcontainer (which it shouldn't, but if so), the second and third tests will fail. The fix is in migration 0001 — verify the explicit `REVOKE UPDATE, DELETE ON audit_log FROM app` happens in migration 0002.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/conftest.py backend/tests/integration/__init__.py backend/tests/integration/test_audit_append_only.py
git commit -m "test(audit): verify app role cannot update or delete audit_log"
```

---

### Task 15: Settings loader service

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/settings_loader.py`
- Create: `backend/tests/unit/test_settings_loader.py`

- [ ] **Step 1: Create `backend/app/services/__init__.py`** (empty file).

- [ ] **Step 2: Create the failing test**

```python
# backend/tests/unit/test_settings_loader.py
import pytest
from sqlalchemy import text

from app.services.settings_loader import SettingNotFound, get_setting, set_setting


def test_get_known_setting_returns_value(admin_session):
    val = get_setting(admin_session, "auth.session_minutes")
    assert val == 15


def test_get_unknown_setting_raises(admin_session):
    with pytest.raises(SettingNotFound):
        get_setting(admin_session, "does.not.exist")


def test_set_setting_updates_and_writes_audit(admin_session):
    set_setting(admin_session, "auth.session_minutes", 20, actor_id=None)
    admin_session.commit()
    assert get_setting(admin_session, "auth.session_minutes") == 20
    audit = admin_session.execute(text(
        "SELECT before, after FROM audit_log WHERE action='system_setting.update' ORDER BY created_at DESC LIMIT 1"
    )).first()
    assert audit is not None
    before, after = audit
    assert before == {"value": 15}
    assert after == {"value": 20}
```

- [ ] **Step 3: Run the test — expect FAIL** (module not found).

- [ ] **Step 4: Create `backend/app/services/settings_loader.py`**

```python
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import SystemSetting


class SettingNotFound(KeyError):
    """Raised when a system_settings key is not present."""


def get_setting(session: Session, key: str) -> Any:
    row = session.get(SystemSetting, key)
    if row is None:
        raise SettingNotFound(key)
    return row.value


def set_setting(session: Session, key: str, value: Any, *, actor_id: uuid.UUID | None) -> None:
    row = session.get(SystemSetting, key)
    before = row.value if row is not None else None
    if row is None:
        row = SystemSetting(key=key, value=value, updated_by=actor_id)
        session.add(row)
    else:
        row.value = value
        row.updated_by = actor_id
    write_audit(
        session,
        actor_id=actor_id,
        action="system_setting.update",
        entity_type="system_setting",
        entity_id=None,
        before=None if before is None else {"value": before},
        after={"value": value},
        context={"key": key},
    )
```

- [ ] **Step 5: Run the test — expect PASS**

Run: `cd backend && uv run pytest tests/unit/test_settings_loader.py -v && cd ..`
Expected: 3 passed.

> If pytest gripes that `admin_session` is missing, you forgot to copy the conftest fixture from Task 14 — go back and verify.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/__init__.py backend/app/services/settings_loader.py backend/tests/unit/test_settings_loader.py
git commit -m "feat(settings): get_setting / set_setting with audit"
```

---

## Phase C — FastAPI app & login flow

### Task 16: FastAPI app factory + health route

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/app/routes/__init__.py`
- Create: `backend/app/routes/health.py`
- Create: `backend/tests/integration/test_health.py`

- [ ] **Step 1: Create `backend/app/routes/__init__.py`** (empty file).

- [ ] **Step 2: Create `backend/app/routes/health.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
```

- [ ] **Step 3: Create `backend/app/main.py`**

Only the health router for now; the auth router is added by Task 18.

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import health as health_routes
from app.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Justice API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_routes.router, prefix="/api")
    return app


app = create_app()
```

> Note: `docs_url=None`, `redoc_url=None`, `openapi_url=None` — these are deliberately off until slice 6 where we re-enable them gated behind the admin role.

- [ ] **Step 4: Create `backend/tests/integration/test_health.py`**

```python
from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 5: Add the `client` fixture to `conftest.py`**

Append to `backend/tests/conftest.py`:

```python
@pytest.fixture()
def client(db_admin_url: str) -> Iterator["TestClient"]:
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
```

- [ ] **Step 6: Run the test — expect PASS**

Run: `cd backend && uv run pytest tests/integration/test_health.py -v && cd ..`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/app/routes/ backend/tests/conftest.py backend/tests/integration/test_health.py
git commit -m "feat(api): fastapi app factory and /api/health"
```

---

### Task 17: Auth dependency `get_current_user`

**Files:**
- Create: `backend/app/auth/deps.py`

- [ ] **Step 1: Create `backend/app/auth/deps.py`**

```python
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.jwt_tokens import InvalidToken, decode_token
from app.db.models import Soldier
from app.db.session import get_session


def _bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_token")
    return auth_header.split(" ", 1)[1].strip()


def get_current_user(request: Request, session: Session = Depends(get_session)) -> Soldier:
    token = _bearer_token(request)
    try:
        payload = decode_token(token)
    except InvalidToken as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token") from exc
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong_token_type")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no_subject")
    user = session.get(Soldier, uuid.UUID(sub))
    if user is None or user.left_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")
    return user
```

> A richer `require(action, target)` dep — scoping by hierarchy and role per Section 5.3 — lands in slice 2 when we have the hierarchy to scope against. This one is sufficient for slice 1's "is the request authenticated?" check.

- [ ] **Step 2: Commit**

```bash
git add backend/app/auth/deps.py
git commit -m "feat(auth): get_current_user FastAPI dependency"
```

---

### Task 18: Login + refresh + logout endpoints (TDD)

**Files:**
- Create: `backend/app/routes/auth.py`
- Create: `backend/tests/integration/test_login.py`

- [ ] **Step 1: Create the failing test**

```python
# backend/tests/integration/test_login.py
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.models import Soldier


def _create_soldier(session: Session, personal_number: str, password: str, role: str = "soldier") -> Soldier:
    s = Soldier(
        personal_number=personal_number,
        full_name=f"Test {personal_number}",
        password_hash=hash_password(password),
        role=role,
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def test_login_with_correct_credentials_returns_tokens(client: TestClient, admin_session: Session):
    _create_soldier(admin_session, "9000001", "hunter2-test")
    r = client.post("/api/auth/login", json={"personal_number": "9000001", "password": "hunter2-test"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    # refresh token comes back as a cookie
    cookies = r.cookies
    assert "refresh_token" in cookies


def test_login_with_wrong_password_returns_401(client: TestClient, admin_session: Session):
    _create_soldier(admin_session, "9000002", "right-password")
    r = client.post("/api/auth/login", json={"personal_number": "9000002", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_credentials"


def test_login_with_unknown_user_returns_401(client: TestClient):
    r = client.post("/api/auth/login", json={"personal_number": "9999999", "password": "anything"})
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_credentials"


def test_login_writes_audit_row_on_success(client: TestClient, admin_session: Session):
    _create_soldier(admin_session, "9000003", "audit-test")
    r = client.post("/api/auth/login", json={"personal_number": "9000003", "password": "audit-test"})
    assert r.status_code == 200
    from sqlalchemy import text
    rows = admin_session.execute(text(
        "SELECT action FROM audit_log WHERE action='auth.login.success' ORDER BY created_at DESC LIMIT 1"
    )).all()
    assert len(rows) == 1


def test_login_writes_audit_row_on_failure(client: TestClient, admin_session: Session):
    _create_soldier(admin_session, "9000004", "audit-test")
    client.post("/api/auth/login", json={"personal_number": "9000004", "password": "wrong"})
    from sqlalchemy import text
    rows = admin_session.execute(text(
        "SELECT action FROM audit_log WHERE action='auth.login.failure' ORDER BY created_at DESC LIMIT 1"
    )).all()
    assert len(rows) == 1
```

- [ ] **Step 2: Run the test — expect FAIL** (module not found).

- [ ] **Step 3: Create `backend/app/routes/auth.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.deps import get_current_user
from app.auth.jwt_tokens import InvalidToken, decode_token, issue_access_token, issue_refresh_token
from app.auth.password import verify_password
from app.db.models import Soldier
from app.db.session import get_session
from app.settings import get_settings


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    personal_number: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool


def _client_context(request: Request) -> dict[str, str]:
    return {
        "ip": request.client.host if request.client else "",
        "user_agent": request.headers.get("user-agent", ""),
    }


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response, session: Session = Depends(get_session)) -> LoginResponse:
    settings = get_settings()
    stmt = select(Soldier).where(Soldier.personal_number == body.personal_number, Soldier.left_at.is_(None))
    soldier = session.execute(stmt).scalar_one_or_none()

    if soldier is None or not verify_password(body.password, soldier.password_hash):
        write_audit(
            session,
            actor_id=soldier.id if soldier is not None else None,
            action="auth.login.failure",
            entity_type="soldier",
            entity_id=soldier.id if soldier is not None else None,
            context={**_client_context(request), "personal_number": body.personal_number},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    refresh = issue_refresh_token(user_id=soldier.id)

    write_audit(
        session,
        actor_id=soldier.id,
        action="auth.login.success",
        entity_type="soldier",
        entity_id=soldier.id,
        context=_client_context(request),
    )
    session.commit()

    response.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True,
        secure=False,  # set to True behind TLS in slice 7; left False so local dev over http works
        samesite="strict",
        path="/api/auth",
    )
    return LoginResponse(access_token=access, must_change_password=soldier.must_change_password)


@router.post("/refresh", response_model=LoginResponse)
def refresh(request: Request, response: Response, session: Session = Depends(get_session)) -> LoginResponse:
    cookie = request.cookies.get("refresh_token")
    if not cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no_refresh_cookie")
    try:
        payload = decode_token(cookie)
    except InvalidToken as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_refresh_token") from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong_token_type")
    import uuid

    soldier = session.get(Soldier, uuid.UUID(payload["sub"]))
    if soldier is None or soldier.left_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")

    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    return LoginResponse(access_token=access, must_change_password=soldier.must_change_password)


@router.post("/logout")
def logout(response: Response, user: Soldier = Depends(get_current_user)) -> dict[str, str]:
    response.delete_cookie(key="refresh_token", path="/api/auth")
    return {"status": "ok"}
```

- [ ] **Step 4: Wire the auth router into `backend/app/main.py`**

Add `from app.routes import auth as auth_routes` near the top and `app.include_router(auth_routes.router, prefix="/api")` right after the health router include.

- [ ] **Step 5: Run the test — expect PASS**

Run: `cd backend && uv run pytest tests/integration/test_login.py -v && cd ..`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/auth.py backend/app/main.py backend/tests/integration/test_login.py
git commit -m "feat(auth): login, refresh, logout endpoints with audit"
```

---

### Task 19: Rate limit the login endpoint

The `limiter` instance lives in its own module to avoid circular imports between `app.main` and `app.routes.auth`.

**Files:**
- Create: `backend/app/rate_limit.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routes/auth.py`

- [ ] **Step 1: Create `backend/app/rate_limit.py`**

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
```

- [ ] **Step 2: Modify `backend/app/main.py`** to register slowapi on the app

Replace the contents with:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.rate_limit import limiter
from app.routes import auth as auth_routes
from app.routes import health as health_routes
from app.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Justice API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    return app


app = create_app()
```

- [ ] **Step 3: Decorate the login endpoint in `backend/app/routes/auth.py`**

Add at the top of the file (alongside the existing imports):

```python
from app.rate_limit import limiter
```

Then decorate the `login` function with a settings-driven limit (so tests can raise the cap via env var without touching code):

```python
@router.post("/login", response_model=LoginResponse)
@limiter.limit(lambda: get_settings().login_rate_limit)
def login(body: LoginRequest, request: Request, response: Response, session: Session = Depends(get_session)) -> LoginResponse:
    ...
```

> `slowapi` requires the `request: Request` parameter to be present (it already is in our handler) — that's how it identifies the client. Passing a no-arg callable lets the limit re-read settings per request.

- [ ] **Step 4: Run all existing tests — expect PASS**

Run: `cd backend && uv run pytest tests/ -v && cd ..`
Expected: all tests still pass (conftest sets `LOGIN_RATE_LIMIT=10000/minute` for the test session).

- [ ] **Step 5: Commit**

```bash
git add backend/app/rate_limit.py backend/app/main.py backend/app/routes/auth.py
git commit -m "feat(auth): rate-limit login via slowapi (configurable per env)"
```

---

### Task 20: Bootstrap script for the first admin

**Files:**
- Create: `backend/app/scripts/__init__.py`
- Create: `backend/app/scripts/bootstrap.py`

- [ ] **Step 1: Create `backend/app/scripts/__init__.py`** (empty file).

- [ ] **Step 2: Create `backend/app/scripts/bootstrap.py`**

```python
"""First-boot script: create the initial admin from env vars, then refuse to run again.

Idempotent: if any soldier with role='admin' already exists, this script exits with
code 0 and prints a no-op message. Otherwise it inserts one admin row using
BOOTSTRAP_ADMIN_PERSONAL_NUMBER / BOOTSTRAP_ADMIN_FULL_NAME / BOOTSTRAP_ADMIN_PASSWORD.

Set must_change_password=True so the soldier is forced to set a new password on
first login.
"""
from __future__ import annotations

import sys

from sqlalchemy import select

from app.auth.password import hash_password
from app.db.models import Soldier
from app.db.session import session_scope
from app.settings import get_settings


def main() -> int:
    settings = get_settings()
    pn = settings.bootstrap_admin_personal_number
    fn = settings.bootstrap_admin_full_name
    pw = settings.bootstrap_admin_password
    if not (pn and fn and pw):
        print("bootstrap: BOOTSTRAP_ADMIN_* env vars not all set; skipping.")
        return 0

    with session_scope() as session:
        existing = session.execute(select(Soldier).where(Soldier.role == "admin").limit(1)).scalar_one_or_none()
        if existing is not None:
            print("bootstrap: an admin already exists; skipping.")
            return 0
        admin = Soldier(
            personal_number=pn,
            full_name=fn,
            password_hash=hash_password(pw),
            role="admin",
            must_change_password=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        print(f"bootstrap: created admin id={admin.id} personal_number={pn}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Smoke test it manually**

Run: `cd backend && uv run python -m app.scripts.bootstrap && cd ..`
Expected: `bootstrap: created admin id=... personal_number=1000001`

Run again immediately:
Run: `cd backend && uv run python -m app.scripts.bootstrap && cd ..`
Expected: `bootstrap: an admin already exists; skipping.`

- [ ] **Step 4: Commit**

```bash
git add backend/app/scripts/
git commit -m "feat(bootstrap): create initial admin from env vars, idempotent"
```

---

### Task 21: Backend Dockerfile

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`

- [ ] **Step 1: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv==0.4.18

COPY pyproject.toml ./
COPY uv.lock* ./

RUN uv sync --no-dev --frozen || uv sync --no-dev

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `backend/.dockerignore`**

```
__pycache__
*.pyc
.venv
.uv-cache
tests
.pytest_cache
.mypy_cache
.ruff_cache
.env
*.md
```

- [ ] **Step 3: Build it to verify the file works**

Run: `docker build -t justice-backend:dev backend/`
Expected: successful build ending in `naming to docker.io/library/justice-backend:dev`.

- [ ] **Step 4: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore
git commit -m "chore(backend): production dockerfile"
```

---

## Phase D — Frontend foundation

### Task 22: Vite + React + TypeScript scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "justice-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "lint": "eslint src --max-warnings 0",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.28.0",
    "axios": "^1.6.8",
    "i18next": "^23.10.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-i18next": "^14.1.0",
    "react-router-dom": "^6.22.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.42.0",
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^14.2.0",
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@typescript-eslint/eslint-plugin": "^7.2.0",
    "@typescript-eslint/parser": "^7.2.0",
    "@vitejs/plugin-react": "^4.2.0",
    "autoprefixer": "^10.4.0",
    "eslint": "^8.57.0",
    "eslint-plugin-react": "^7.34.0",
    "eslint-plugin-react-hooks": "^4.6.0",
    "jsdom": "^24.0.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "tailwindcss-rtl": "^0.9.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0",
    "vitest": "^1.4.0"
  }
}
```

- [ ] **Step 2: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noImplicitAny": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "esModuleInterop": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "allowSyntheticDefaultImports": true,
    "baseUrl": "src",
    "paths": {
      "@/*": ["./*"]
    }
  },
  "include": ["src", "tests"]
}
```

- [ ] **Step 3: Create `frontend/vite.config.ts`**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: { port: 5173, host: "0.0.0.0" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
  } as unknown as Record<string, unknown>,
});
```

- [ ] **Step 4: Create `frontend/index.html`**

```html
<!DOCTYPE html>
<html lang="he" dir="rtl">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ניהול תורנויות</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Create `frontend/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import "./i18n";
import "./styles/globals.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 6: Create `frontend/src/App.tsx`** (placeholder — fleshed out in Task 27)

```tsx
export default function App() {
  return <div>טוען...</div>;
}
```

- [ ] **Step 7: Install deps**

Run: `cd frontend && pnpm install && cd ..`
Expected: `Done in ...`

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html frontend/src/main.tsx frontend/src/App.tsx frontend/pnpm-lock.yaml
git commit -m "chore(frontend): vite + react + ts scaffold (he-IL, RTL html)"
```

---

### Task 23: Tailwind + RTL

**Files:**
- Create: `frontend/tailwind.config.cjs`
- Create: `frontend/postcss.config.cjs`
- Create: `frontend/src/styles/globals.css`

- [ ] **Step 1: Create `frontend/tailwind.config.cjs`**

```js
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Heebo", "Arial", "sans-serif"],
      },
      colors: {
        approved: "#16a34a",
        pending: "#d97706",
        rejected: "#dc2626",
        cancelled: "#6b7280",
      },
    },
  },
  plugins: [require("tailwindcss-rtl")],
};
```

- [ ] **Step 2: Create `frontend/postcss.config.cjs`**

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 3: Create `frontend/src/styles/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@import url("https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;700&display=swap");

html, body, #root {
  height: 100%;
}

body {
  font-family: "Heebo", Arial, sans-serif;
  background: #f8fafc;
  color: #0f172a;
}
```

- [ ] **Step 4: Verify build still works**

Run: `cd frontend && pnpm build && cd ..`
Expected: build succeeds and produces `dist/`.

- [ ] **Step 5: Commit**

```bash
git add frontend/tailwind.config.cjs frontend/postcss.config.cjs frontend/src/styles/globals.css
git commit -m "chore(frontend): tailwind + RTL plugin + heebo font"
```

---

### Task 24: i18n with Hebrew strings

**Files:**
- Create: `frontend/src/i18n/index.ts`
- Create: `frontend/src/i18n/he.json`

- [ ] **Step 1: Create `frontend/src/i18n/he.json`**

```json
{
  "app": {
    "title": "ניהול תורנויות",
    "loading": "טוען..."
  },
  "login": {
    "title": "התחברות",
    "personal_number_label": "מספר אישי",
    "personal_number_placeholder": "לדוגמה: 1234567",
    "password_label": "סיסמה",
    "submit": "התחבר",
    "submitting": "מתחבר...",
    "errors": {
      "invalid_credentials": "מספר אישי או סיסמה שגויים",
      "network": "שגיאת רשת. נסה שוב.",
      "rate_limited": "יותר מדי ניסיונות. נסה שוב בעוד מספר דקות."
    }
  },
  "home": {
    "welcome": "שלום, {{name}}",
    "logout": "יציאה"
  },
  "common": {
    "must_change_password": "עליך לשנות את הסיסמה לפני המשך השימוש."
  }
}
```

- [ ] **Step 2: Create `frontend/src/i18n/index.ts`**

```ts
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import he from "./he.json";

i18n
  .use(initReactI18next)
  .init({
    resources: { he: { translation: he } },
    lng: "he",
    fallbackLng: "he",
    interpolation: { escapeValue: false },
  });

export default i18n;
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/
git commit -m "chore(frontend): i18n bundle with Hebrew strings"
```

---

### Task 25: API client + auth context

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/auth/AuthContext.tsx`
- Create: `frontend/src/auth/ProtectedRoute.tsx`

- [ ] **Step 1: Create `frontend/src/api/client.ts`**

```ts
import axios, { AxiosError } from "axios";

const baseURL = import.meta.env.VITE_API_BASE ?? "/api";

export const api = axios.create({
  baseURL,
  withCredentials: true,
});

let accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

let refreshing: Promise<string> | null = null;

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const originalRequest = error.config as (typeof error.config & { _retry?: boolean }) | undefined;
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true;
      try {
        if (!refreshing) {
          refreshing = api.post<{ access_token: string }>("/auth/refresh").then((r) => {
            setAccessToken(r.data.access_token);
            return r.data.access_token;
          }).finally(() => {
            refreshing = null;
          });
        }
        await refreshing;
        return api.request(originalRequest);
      } catch {
        setAccessToken(null);
        throw error;
      }
    }
    throw error;
  },
);
```

- [ ] **Step 2: Create `frontend/src/api/auth.ts`**

```ts
import { api } from "./client";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
}

export async function login(personal_number: string, password: string): Promise<LoginResponse> {
  const r = await api.post<LoginResponse>("/auth/login", { personal_number, password });
  return r.data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
}
```

- [ ] **Step 3: Create `frontend/src/auth/AuthContext.tsx`**

```tsx
import { createContext, useCallback, useContext, useMemo, useState, ReactNode } from "react";

import { login as apiLogin, logout as apiLogout, LoginResponse } from "../api/auth";
import { setAccessToken } from "../api/client";

interface AuthState {
  loggedIn: boolean;
  mustChangePassword: boolean;
}

interface AuthContextValue extends AuthState {
  login: (personal_number: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ loggedIn: false, mustChangePassword: false });

  const login = useCallback(async (personal_number: string, password: string) => {
    const r: LoginResponse = await apiLogin(personal_number, password);
    setAccessToken(r.access_token);
    setState({ loggedIn: true, mustChangePassword: r.must_change_password });
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setAccessToken(null);
      setState({ loggedIn: false, mustChangePassword: false });
    }
  }, []);

  const value = useMemo(() => ({ ...state, login, logout }), [state, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth used outside AuthProvider");
  return ctx;
}
```

- [ ] **Step 4: Create `frontend/src/auth/ProtectedRoute.tsx`**

```tsx
import { Navigate, Outlet } from "react-router-dom";

import { useAuth } from "./AuthContext";

export default function ProtectedRoute() {
  const { loggedIn } = useAuth();
  if (!loggedIn) return <Navigate to="/login" replace />;
  return <Outlet />;
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/ frontend/src/auth/
git commit -m "feat(frontend): api client + auth context + protected route"
```

---

### Task 26: Login page

**Files:**
- Create: `frontend/src/pages/LoginPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/LoginPage.tsx`**

```tsx
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AxiosError } from "axios";

import { useAuth } from "../auth/AuthContext";

type ErrKey = "invalid_credentials" | "network" | "rate_limited" | null;

export default function LoginPage() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();

  const [personalNumber, setPersonalNumber] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorKey, setErrorKey] = useState<ErrKey>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErrorKey(null);
    setSubmitting(true);
    try {
      await login(personalNumber, password);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof AxiosError) {
        if (err.response?.status === 401) setErrorKey("invalid_credentials");
        else if (err.response?.status === 429) setErrorKey("rate_limited");
        else setErrorKey("network");
      } else {
        setErrorKey("network");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <form onSubmit={onSubmit} className="w-full max-w-sm bg-white shadow rounded-lg p-6 space-y-4" data-testid="login-form">
        <h1 className="text-2xl font-bold text-center">{t("login.title")}</h1>

        <label className="block">
          <span className="text-sm font-medium">{t("login.personal_number_label")}</span>
          <input
            type="text"
            inputMode="numeric"
            autoComplete="username"
            required
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200 p-2 border"
            value={personalNumber}
            onChange={(e) => setPersonalNumber(e.target.value)}
            data-testid="personal-number-input"
            placeholder={t("login.personal_number_placeholder")}
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium">{t("login.password_label")}</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200 p-2 border"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="password-input"
          />
        </label>

        {errorKey && (
          <div className="text-rejected text-sm" data-testid="login-error">
            {t(`login.errors.${errorKey}`)}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium py-2 rounded-md"
          data-testid="login-submit"
        >
          {submitting ? t("login.submitting") : t("login.submit")}
        </button>
      </form>
    </main>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx
git commit -m "feat(frontend): login page"
```

---

### Task 27: Home page + Layout + wire up routes

**Files:**
- Create: `frontend/src/pages/HomePage.tsx`
- Create: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create `frontend/src/components/Layout.tsx`**

```tsx
import { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { logout, mustChangePassword } = useAuth();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <h1 className="text-lg font-bold">{t("app.title")}</h1>
          <button onClick={() => logout()} className="text-sm text-indigo-600 hover:text-indigo-800" data-testid="logout-button">
            {t("home.logout")}
          </button>
        </div>
      </header>
      {mustChangePassword && (
        <div className="bg-pending/10 border-b border-pending/30 text-pending px-4 py-2 text-sm" data-testid="must-change-password-banner">
          {t("common.must_change_password")}
        </div>
      )}
      <main className="flex-1 max-w-6xl mx-auto w-full px-4 py-6">{children}</main>
    </div>
  );
}
```

- [ ] **Step 2: Create `frontend/src/pages/HomePage.tsx`**

```tsx
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";

export default function HomePage() {
  const { t } = useTranslation();
  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold">{t("home.welcome", { name: "" })}</h2>
        <p className="text-gray-600 mt-2">
          זהו עמוד הבית הראשוני. תכנים אמיתיים יתווספו ב-Slice 2 והלאה.
        </p>
      </section>
    </Layout>
  );
}
```

- [ ] **Step 3: Replace `frontend/src/App.tsx`**

```tsx
import { Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<HomePage />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}
```

- [ ] **Step 4: Verify the frontend builds**

Run: `cd frontend && pnpm build && cd ..`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/HomePage.tsx frontend/src/components/Layout.tsx
git commit -m "feat(frontend): layout shell + home page placeholder + routes wired"
```

---

### Task 28: Frontend Dockerfile

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/.dockerignore`

- [ ] **Step 1: Create `frontend/Dockerfile`**

```dockerfile
FROM node:20-alpine AS build

WORKDIR /app

RUN npm install -g pnpm@9

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# --- Runtime stage (static files served by Caddy in slice 7; dev image just previews)
FROM node:20-alpine AS runtime
WORKDIR /app
COPY --from=build /app/dist ./dist
RUN npm install -g serve
EXPOSE 5173
CMD ["serve", "-s", "dist", "-l", "5173"]
```

- [ ] **Step 2: Create `frontend/.dockerignore`**

```
node_modules
dist
.vite
.env
*.md
tests
playwright-report
test-results
```

- [ ] **Step 3: Build to verify**

Run: `docker build -t justice-frontend:dev frontend/`
Expected: successful multi-stage build.

- [ ] **Step 4: Commit**

```bash
git add frontend/Dockerfile frontend/.dockerignore
git commit -m "chore(frontend): production dockerfile (multi-stage)"
```

---

## Phase E — End-to-end test & CI

### Task 29: Playwright e2e for login

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/tests/e2e/login.spec.ts`
- Create: `frontend/tests/setup.ts`

- [ ] **Step 1: Create `frontend/tests/setup.ts`** (Vitest needs this)

```ts
import "@testing-library/jest-dom";
```

- [ ] **Step 2: Create `frontend/playwright.config.ts`**

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
});
```

- [ ] **Step 3: Install Playwright browsers**

Run: `cd frontend && pnpm exec playwright install chromium && cd ..`
Expected: chromium downloads.

- [ ] **Step 4: Create `frontend/tests/e2e/login.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

test.describe("login", () => {
  test("login with bootstrap admin lands on home", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("personal-number-input").fill("1000001");
    await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL("/");
    await expect(page.getByTestId("must-change-password-banner")).toBeVisible();
    await expect(page.getByTestId("logout-button")).toBeVisible();
  });

  test("login with wrong password shows Hebrew error", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("personal-number-input").fill("1000001");
    await page.getByTestId("password-input").fill("wrong-password");
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("login-error")).toHaveText("מספר אישי או סיסמה שגויים");
  });
});
```

- [ ] **Step 5: Run the e2e manually**

In one terminal: `cd backend && uv run uvicorn app.main:app --port 8000`
In another terminal: `cd frontend && pnpm dev`
In a third terminal: `cd frontend && pnpm test:e2e`
Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/playwright.config.ts frontend/tests/
git commit -m "test(frontend): playwright e2e for login"
```

---

### Task 30: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Install uv
        run: pip install uv==0.4.18
      - name: Install deps
        working-directory: backend
        run: uv sync --extra dev
      - name: Lint
        working-directory: backend
        run: |
          uv run ruff check app tests
          uv run ruff format --check app tests
      - name: Type check
        working-directory: backend
        run: uv run mypy app
      - name: Tests
        working-directory: backend
        env:
          JWT_SECRET: ci-secret-32-bytes-of-padding-___xx
        run: uv run pytest -q

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - uses: pnpm/action-setup@v3
        with: { version: 9 }
      - name: Install
        working-directory: frontend
        run: pnpm install --frozen-lockfile
      - name: Lint
        working-directory: frontend
        run: pnpm lint
      - name: Type check
        working-directory: frontend
        run: pnpm exec tsc --noEmit
      - name: Unit tests
        working-directory: frontend
        run: pnpm test
      - name: Build
        working-directory: frontend
        run: pnpm build
```

> Playwright e2e is intentionally not in CI for slice 1 (it needs a running backend + DB; CI orchestration is a slice-7 task). It's expected that engineers run it locally before pushing.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: backend (ruff/mypy/pytest) + frontend (lint/types/test/build)"
```

---

### Task 31: Final integration smoke test (manual)

- [ ] **Step 1: Stop any running containers and start fresh**

Run: `docker-compose down -v && docker-compose up -d db`
Wait ~10s for healthcheck.

- [ ] **Step 2: Apply migrations from scratch**

Run: `cd backend && uv run alembic upgrade head && cd ..`
Expected: 4 migrations applied (`0001` through `0004`).

- [ ] **Step 3: Bootstrap the initial admin**

Run: `cd backend && uv run python -m app.scripts.bootstrap && cd ..`
Expected: `bootstrap: created admin id=... personal_number=1000001`

- [ ] **Step 4: Start backend and frontend**

Terminal A: `cd backend && uv run uvicorn app.main:app --reload --port 8000`
Terminal B: `cd frontend && pnpm dev`

- [ ] **Step 5: Verify login through the browser**

Open `http://localhost:5173/login`.
Enter `1000001` / `ChangeMeOnFirstLogin!`.
Expected: redirected to `/`, header shows "ניהול תורנויות", "must change password" banner visible.

- [ ] **Step 6: Verify the login event was audited**

Run: `docker-compose exec db psql -U db_admin -d cod2 -c "SELECT actor_id, action, context FROM audit_log ORDER BY created_at DESC LIMIT 5;"`
Expected: at least one row with `action='auth.login.success'` and a non-null `actor_id`.

- [ ] **Step 7: Verify the audit log cannot be tampered with**

Run: `docker-compose exec db psql -U app -d cod2 -c "DELETE FROM audit_log;"`
Expected: `ERROR: permission denied for table audit_log`.

> If this *succeeds*, migration 0002 was incorrect — go back and verify the explicit `REVOKE ALL ... GRANT SELECT, INSERT` lines actually executed.

- [ ] **Step 8: Run the entire test suite once more**

Run: `cd backend && uv run pytest -q && cd ..`
Expected: all tests pass.

Run: `cd frontend && pnpm test && pnpm build && cd ..`
Expected: tests pass and build succeeds.

- [ ] **Step 9: Final commit (if any unrelated artefacts changed)**

```bash
git status
# If anything untracked or modified, decide whether to commit; otherwise stop.
```

---

## Definition of done for Slice 1

- [ ] All 31 tasks above completed and committed in order.
- [ ] `docker-compose up -d db && cd backend && uv run alembic upgrade head && uv run python -m app.scripts.bootstrap` brings the system from zero to a working admin.
- [ ] `uv run uvicorn app.main:app` + `pnpm dev` produces a working login + home flow in the browser.
- [ ] All backend tests pass (unit + integration).
- [ ] All frontend unit + Playwright e2e tests pass.
- [ ] CI is green on the main branch.
- [ ] The audit log cannot be modified or deleted by the `app` Postgres role.
- [ ] No environment value is hard-coded — everything tunable comes from `.env` (deployment-level) or `system_settings` (runtime).
- [ ] README documents the quickstart end-to-end.

## What slice 1 deliberately does NOT include

- Hierarchy, soldier CRUD beyond the bootstrap admin, "must change password" enforcement flow → **slice 2**.
- Anything domain-specific: duty types, locations, exemptions, constraints, duties, scoring → **slices 3-5**.
- System settings UI, audit log UI → **slice 6**.
- Production hardening (Caddy, encrypted backups, runbook, Playwright in CI) → **slice 7**.

When you start slice 2, write its plan in `docs/superpowers/plans/<date>-slice-2-hierarchy-and-soldiers.md` following the same template.

---

*End of plan.*
