# Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the self-hosted Justice system for production use with hundreds of users — fixing security, performance, data-integrity, and infrastructure gaps identified in the audit.

**Architecture:** All fixes are backend-only except for the deployment artifacts. No managed cloud services — everything runs self-hosted via Docker Compose. Changes are grouped into six independent tasks that can be committed separately.

**Tech Stack:** FastAPI, SQLAlchemy 2, PostgreSQL 16, Alembic, Docker Compose, nginx (new), Python 3.12.

---

## File map

| File | Change |
|---|---|
| `backend/alembic/versions/0062_fk_indexes.py` | New — add indexes on FK columns |
| `backend/alembic/versions/0063_check_constraints.py` | New — date CHECK constraints |
| `backend/app/db/session.py` | Add connection pool settings |
| `backend/app/routes/health.py` | Split into `/live` + `/ready` |
| `backend/app/routes/soldiers.py` | Fix N+1 list; add auth to /ranks |
| `backend/app/routes/hierarchy.py` | Fix N+1 in _out() |
| `backend/app/routes/auth.py` | Fix N+1 register_nodes; atomic lockout |
| `backend/app/routes/exemption_requests.py` | Sanitise filename; rate-limit download |
| `backend/app/services/soldiers.py` | Stronger password policy |
| `backend/app/main.py` | Request-size middleware; run solver in threadpool |
| `backend/app/logging_config.py` | Add JSON formatter for structured logging |
| `backend/app/middleware/security_headers.py` | Default HSTS to 1 year |
| `deploy/nginx.conf` | New — reverse-proxy + TLS termination config |
| `deploy/docker-compose.prod.yml` | New — production compose (no --reload, nginx, etc.) |
| `deploy/.env.production.example` | New — production env template with instructions |
| `deploy/backup.sh` | New — daily pg_dump backup script |

---

## Task 1: Database — FK indexes

**Files:**
- Create: `backend/alembic/versions/0062_fk_indexes.py`

- [ ] **Step 1: Create migration**

```python
# backend/alembic/versions/0062_fk_indexes.py
"""add FK indexes for performance

Revision ID: 0062
Revises: 0061
Create Date: 2026-06-29
"""
from alembic import op

revision = '0062'
down_revision = '0061'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_soldiers_hierarchy_node_id", "soldiers", ["hierarchy_node_id"])
    op.create_index("ix_duty_assignments_soldier_id", "duty_assignments", ["soldier_id"])
    op.create_index("ix_duty_assignments_duty_type_id", "duty_assignments", ["duty_type_id"])
    op.create_index("ix_soldier_exemptions_soldier_id", "soldier_exemptions", ["soldier_id"])
    op.create_index("ix_algorithm_jobs_created_by", "algorithm_jobs", ["created_by"])
    op.create_index("ix_personal_constraints_soldier_id", "personal_constraints", ["soldier_id"])


def downgrade() -> None:
    op.drop_index("ix_personal_constraints_soldier_id", "personal_constraints")
    op.drop_index("ix_algorithm_jobs_created_by", "algorithm_jobs")
    op.drop_index("ix_soldier_exemptions_soldier_id", "soldier_exemptions")
    op.drop_index("ix_duty_assignments_duty_type_id", "duty_assignments")
    op.drop_index("ix_duty_assignments_soldier_id", "duty_assignments")
    op.drop_index("ix_soldiers_hierarchy_node_id", "soldiers")
```

- [ ] **Step 2: Apply and verify**

```bash
cd backend
alembic upgrade head
# Expected: "Running upgrade 0061 -> 0062, add FK indexes for performance"
```

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0062_fk_indexes.py
git commit -m "perf: add FK indexes on high-frequency query columns"
```

---

## Task 2: Fix N+1 queries

**Files:**
- Modify: `backend/app/routes/soldiers.py` (lines 268–283)
- Modify: `backend/app/routes/hierarchy.py` (lines 88–105)
- Modify: `backend/app/routes/auth.py` (lines 296–315)

### 2a — soldiers list

The `list_soldiers` function currently calls `_node_of(session, s)` in a Python loop.

- [ ] **Step 1: Read `_node_of` to understand what it does**

```bash
grep -n "_node_of" backend/app/routes/soldiers.py | head -10
```

- [ ] **Step 2: Replace the looping N+1 with a single IN query**

In `backend/app/routes/soldiers.py`, find the admin branch (around line 267) and the scoped branch (around line 276). Replace both so that hierarchy nodes are bulk-loaded:

```python
# At the top of the file, add this import if not present:
from sqlalchemy import select

# Replace the admin list block (around line 267):
    if user.role == "admin":
        rows = session.execute(select(Soldier)).scalars().all()
        # Bulk-load all hierarchy nodes once
        node_ids = {s.hierarchy_node_id for s in rows if s.hierarchy_node_id}
        nodes_by_id = {}
        if node_ids:
            nodes_by_id = {
                n.id: n for n in session.execute(
                    select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
                ).scalars().all()
            }
        return [
            _out(s, include_private=False, telegram_linked=s.id in linked_ids)
            for s in rows
        ]
```

Note: Check what `_node_of` actually does and whether it is used in `_out`. If `_out` doesn't call `_node_of`, only the scoped branch needs the fix. Read the actual code before editing.

- [ ] **Step 3: Fix the scoped branch**

In the non-admin branch (around line 276), replace:
```python
    rows = session.execute(select(Soldier)).scalars().all()
    out: list[SoldierOut] = []
    for s in rows:
        node = _node_of(session, s)
        in_scope = node is not None and any(r in node.path_ids for r in roots)
        include_private = in_scope or s.id == user.id
        out.append(_out(s, include_private=include_private, telegram_linked=s.id in linked_ids))
    return out
```

With:
```python
    rows = session.execute(select(Soldier)).scalars().all()
    node_ids = {s.hierarchy_node_id for s in rows if s.hierarchy_node_id}
    nodes_by_id: dict[uuid.UUID, HierarchyNode] = {}
    if node_ids:
        nodes_by_id = {
            n.id: n for n in session.execute(
                select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
            ).scalars().all()
        }
    out: list[SoldierOut] = []
    for s in rows:
        node = nodes_by_id.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        in_scope = node is not None and any(r in node.path_ids for r in roots)
        include_private = in_scope or s.id == user.id
        out.append(_out(s, include_private=include_private, telegram_linked=s.id in linked_ids))
    return out
```

### 2b — hierarchy _out()

- [ ] **Step 4: Fix the _out helper in hierarchy.py**

In `backend/app/routes/hierarchy.py`, find the `list_nodes` or equivalent caller that calls `_out()` in a loop. Bulk-load commanders and DM scopes before the loop, then pass them in.

Find the list endpoint (likely `get_nodes` or similar). Before the loop that calls `_out`, add:

```python
# Bulk-load all commanders in one query
commander_ids = {n.commander_id for n in all_nodes if n.commander_id}
commanders_by_id: dict[uuid.UUID, Soldier] = {}
if commander_ids:
    commanders_by_id = {
        s.id: s for s in session.execute(
            select(Soldier).where(Soldier.id.in_(commander_ids))
        ).scalars().all()
    }

# Bulk-load all DM scopes
all_node_ids = {n.id for n in all_nodes}
dm_rows = session.execute(
    select(DutyManagerScope, Soldier.full_name)
    .join(Soldier, Soldier.id == DutyManagerScope.duty_manager_id)
    .where(DutyManagerScope.hierarchy_node_id.in_(all_node_ids))
).all()
dms_by_node: dict[uuid.UUID, list[DutyManagerEntryOut]] = {}
for entry, name in dm_rows:
    dms_by_node.setdefault(entry.hierarchy_node_id, []).append(
        DutyManagerEntryOut(scope_id=entry.id, soldier_id=entry.duty_manager_id, name=name)
    )
```

Then update `_out()` to accept `commander: Soldier | None` and `duty_managers: list[DutyManagerEntryOut]` as parameters (duty_managers already has an optional param — just always pass it). Update the call sites.

### 2c — register_nodes N+1

- [ ] **Step 5: Fix register_nodes in auth.py (around line 296)**

Replace:
```python
    nodes = session.execute(sa_select(HierarchyNode)).scalars().all()
    result = []
    for n in nodes:
        commander_name: str | None = None
        if n.commander_id:
            s = session.get(Soldier, n.commander_id)
            commander_name = s.full_name if s else None
        result.append(NodeOut(...))
    return result
```

With:
```python
    from sqlalchemy import select as sa_select
    nodes = session.execute(sa_select(HierarchyNode)).scalars().all()
    commander_ids = {n.commander_id for n in nodes if n.commander_id}
    commanders: dict[uuid.UUID, str] = {}
    if commander_ids:
        commanders = {
            s.id: s.full_name
            for s in session.execute(
                sa_select(Soldier).where(Soldier.id.in_(commander_ids))
            ).scalars().all()
        }
    return [
        NodeOut(
            id=n.id, name=n.name, level=n.level,
            path_ids=n.path_ids,
            commander_name=commanders.get(n.commander_id) if n.commander_id else None,
            parent_id=n.parent_id,
        )
        for n in nodes
    ]
```

- [ ] **Step 6: Run tests**

```bash
cd backend
pytest -m "hierarchy or soldiers or auth" -q
# Expected: all pass
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/soldiers.py backend/app/routes/hierarchy.py backend/app/routes/auth.py
git commit -m "perf: fix N+1 queries in soldiers list, hierarchy nodes, and register nodes"
```

---

## Task 3: Security code fixes

**Files:**
- Modify: `backend/app/routes/soldiers.py` (line 287)
- Modify: `backend/app/routes/exemption_requests.py` (lines 300–301, ~line 346)
- Modify: `backend/app/routes/auth.py` (lines 135–145)
- Modify: `backend/app/services/soldiers.py` (lines 16–29)
- Modify: `backend/app/main.py`

### 3a — auth on /ranks

- [ ] **Step 1: Add auth dependency to /ranks**

In `backend/app/routes/soldiers.py` around line 287:

```python
# Before:
@router.get("/ranks")
def get_ranks() -> dict[str, list[str]]:
    return {"enlisted": ENLISTED_RANKS, "officers": OFFICER_RANKS}

# After:
@router.get("/ranks")
def get_ranks(_user: Soldier = Depends(require_password_changed)) -> dict[str, list[str]]:
    return {"enlisted": ENLISTED_RANKS, "officers": OFFICER_RANKS}
```

Make sure `require_password_changed` is already imported (it is — check existing imports at top of file).

### 3b — atomic account lockout

- [ ] **Step 2: Replace read-modify-write lockout with atomic UPDATE**

In `backend/app/routes/auth.py`, add this import at the top if not present:
```python
from sqlalchemy import update as sa_update, func, case as sa_case
```

Replace the failed-login block (lines 135–145):
```python
    if not verify_password(body.password, soldier.password_hash):
        count = getattr(soldier, "failed_login_count", 0) + 1
        soldier.failed_login_count = count
        if count >= _LOCKOUT_THRESHOLD:
            soldier.locked_until = _now_utc + _td(minutes=_LOCKOUT_MINUTES)
            soldier.failed_login_count = 0
        write_audit(...)
        session.commit()
        raise HTTPException(...)
```

With:
```python
    if not verify_password(body.password, soldier.password_hash):
        # Atomic increment to avoid race condition under parallel brute-force
        session.execute(
            sa_update(Soldier)
            .where(Soldier.id == soldier.id)
            .values(
                failed_login_count=sa_case(
                    (Soldier.failed_login_count + 1 >= _LOCKOUT_THRESHOLD, 0),
                    else_=Soldier.failed_login_count + 1,
                ),
                locked_until=sa_case(
                    (Soldier.failed_login_count + 1 >= _LOCKOUT_THRESHOLD,
                     _now_utc + _td(minutes=_LOCKOUT_MINUTES)),
                    else_=Soldier.locked_until,
                ),
            )
        )
        write_audit(
            session, actor_id=soldier.id, action="auth.login.failure", entity_type="soldier",
            entity_id=soldier.id, context={**_client_context(request), "personal_number": body.personal_number},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
```

### 3c — filename sanitisation

- [ ] **Step 3: Sanitise uploaded filename**

In `backend/app/routes/exemption_requests.py`, add at the top:
```python
import re
```

Replace line 301:
```python
# Before:
        file_name=file.filename or "file",

# After:
        file_name=re.sub(r"[^\w.\-]", "_", (file.filename or "file"))[:200],
```

### 3d — rate-limit file download

- [ ] **Step 4: Add rate limit to download endpoint**

In `backend/app/routes/exemption_requests.py`, find the download endpoint (around line 346):
```python
# Before:
@router.get("/exemption-requests/{request_id}/files/{file_id}")
def download_exemption_file(

# After:
@router.get("/exemption-requests/{request_id}/files/{file_id}")
@limiter.limit("30/minute")
def download_exemption_file(
    request: Request,  # add Request as first param if not already there
```

Make sure `limiter` and `Request` are imported (check existing imports — they should be since other routes in the file use them).

### 3e — password complexity

- [ ] **Step 5: Strengthen password policy in soldiers.py**

Replace `validate_password` in `backend/app/services/soldiers.py`:

```python
import re

MIN_PASSWORD_LENGTH = 10

def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    classes = [
        bool(re.search(r"[A-Za-z]", password)),   # at least one letter
        bool(re.search(r"[0-9]", password)),        # at least one digit
    ]
    if not all(classes):
        raise PasswordPolicyError("password must contain at least one letter and one digit")
```

Note: Keep policy achievable — soldiers using Hebrew keyboards may not have special chars easily. Letters + digits is a sensible minimum without frustrating users.

### 3f — request body size limit

- [ ] **Step 6: Add body size middleware to main.py**

In `backend/app/main.py`, after the existing imports add:
```python
from starlette.responses import Response as StarletteResponse
```

Add this class before `create_app()` or before the `app = FastAPI(...)` line:
```python
class _BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests over 50 MB to prevent memory exhaustion from large uploads."""
    _LIMIT = 50 * 1024 * 1024  # 50 MB

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self._LIMIT:
            return StarletteResponse("Payload too large", status_code=413)
        return await call_next(request)
```

Then register it. Find where other middleware is added (e.g. `app.add_middleware(CORSMiddleware, ...)`) and add:
```python
app.add_middleware(_BodySizeLimitMiddleware)
```

You'll also need:
```python
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
```

(Check if these are already imported.)

- [ ] **Step 7: Run tests**

```bash
cd backend
pytest -m "auth or soldiers" -q
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/routes/soldiers.py backend/app/routes/exemption_requests.py \
        backend/app/routes/auth.py backend/app/services/soldiers.py backend/app/main.py
git commit -m "fix: security hardening — atomic lockout, filename sanitise, body size limit, password policy, ranks auth"
```

---

## Task 4: Data integrity — CHECK constraints

**Files:**
- Create: `backend/alembic/versions/0063_check_constraints.py`

- [ ] **Step 1: Check for existing violations before adding constraints**

```bash
cd backend
# Activate venv first: .venv\Scripts\activate (Windows)
python - <<'EOF'
from app.db.session import session_scope
from sqlalchemy import text
with session_scope() as s:
    bad = s.execute(text(
        "SELECT COUNT(*) FROM duty_assignments WHERE start_date > end_date"
    )).scalar()
    print(f"Violations: {bad}")
EOF
# Expected: Violations: 0
```

If violations > 0, fix the data first before adding the constraint.

- [ ] **Step 2: Create migration**

```python
# backend/alembic/versions/0063_check_constraints.py
"""add CHECK constraints for date integrity

Revision ID: 0063
Revises: 0062
Create Date: 2026-06-29
"""
from alembic import op

revision = '0063'
down_revision = '0062'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_duty_assignments_dates",
        "duty_assignments",
        "start_date <= end_date",
    )
    op.create_check_constraint(
        "ck_personal_constraints_dates",
        "personal_constraints",
        "start_date <= end_date",
    )
    op.create_check_constraint(
        "ck_exemption_requests_dates",
        "exemption_requests",
        "start_date <= end_date OR end_date IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_exemption_requests_dates", "exemption_requests")
    op.drop_constraint("ck_personal_constraints_dates", "personal_constraints")
    op.drop_constraint("ck_duty_assignments_dates", "duty_assignments")
```

- [ ] **Step 3: Apply**

```bash
alembic upgrade head
# Expected: "Running upgrade 0062 -> 0063, add CHECK constraints for date integrity"
```

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0063_check_constraints.py
git commit -m "fix: add CHECK constraints to prevent start_date > end_date in duty/constraint/exemption tables"
```

---

## Task 5: Infrastructure — connection pool, health probes, solver threadpool, logging, HSTS

**Files:**
- Modify: `backend/app/db/session.py`
- Modify: `backend/app/routes/health.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/logging_config.py`
- Modify: `backend/app/middleware/security_headers.py`

### 5a — connection pool

- [ ] **Step 1: Configure pool in session.py**

Replace `create_engine(...)` in `backend/app/db/session.py`:

```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    pool_size=20,
    max_overflow=10,
    pool_recycle=3600,  # recycle connections every hour
    pool_timeout=30,    # raise after 30s waiting for a connection
)
```

### 5b — liveness / readiness split

- [ ] **Step 2: Split health endpoint**

Replace `backend/app/routes/health.py` entirely:

```python
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from app.db.session import get_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def liveness() -> dict[str, str]:
    """Liveness probe — no external deps. Returns 200 if process is alive."""
    return {"status": "alive"}


@router.get("/ready")
def readiness(session: Session = Depends(get_session)) -> JSONResponse:
    """Readiness probe — checks DB. Returns 503 if not ready to serve traffic."""
    try:
        session.execute(text("SELECT 1"))
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        return JSONResponse({"status": "not_ready", "error": str(exc)}, status_code=503)


@router.get("")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    """Legacy health endpoint — kept for backward compatibility."""
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
```

### 5c — solver in threadpool

- [ ] **Step 3: Move solver to threadpool in algorithm.py**

In `backend/app/routes/algorithm.py`, find the import area and add:
```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

_solver_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="solver")
```

Find where `background_tasks.add_task(run_algorithm_job, job.id, actor_id)` is called (line 505). Replace it:

```python
    async def _run_in_thread():
        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(_solver_executor, run_algorithm_job, job.id, actor_id),
                timeout=3600,  # 1-hour hard ceiling; solver has its own time_limit_seconds
            )
        except asyncio.TimeoutError:
            # job runner already handles DB updates; this is a safety net
            pass

    background_tasks.add_task(_run_in_thread)
```

Note: If `run_algorithm_job` is already synchronous and uses its own DB session, this is safe. Verify `run_algorithm_job`'s signature before editing.

### 5d — structured logging

- [ ] **Step 4: Add JSON log handler for production**

In `backend/app/logging_config.py`, add a JSON formatter that is enabled by `LOG_FORMAT=json` env var:

```python
import json
from datetime import datetime, timezone

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
        }, ensure_ascii=False)
```

In `setup_logging`, choose formatter based on env var:
```python
def setup_logging(log_filename: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    use_json = os.environ.get("LOG_FORMAT", "").lower() == "json"
    formatter = _JsonFormatter() if use_json else logging.Formatter(_FORMAT)
    # ... rest unchanged
```

Set `LOG_FORMAT=json` in the production `.env`.

### 5e — HSTS default

- [ ] **Step 5: Default HSTS to 1 year in security_headers.py**

Change the default in `backend/app/middleware/security_headers.py`:

```python
# Before:
_HSTS_MAX_AGE = int(os.environ.get("HSTS_MAX_AGE", "0"))

# After:
_HSTS_MAX_AGE = int(os.environ.get("HSTS_MAX_AGE", "31536000"))  # 1 year default
```

Note: This is fine for self-hosted with TLS. If running HTTP-only behind a terminating proxy that strips headers, set `HSTS_MAX_AGE=0` in the env.

- [ ] **Step 6: Run full test suite**

```bash
cd backend
pytest -q
# Expected: all pass (or same baseline as before)
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/session.py backend/app/routes/health.py backend/app/routes/algorithm.py \
        backend/app/logging_config.py backend/app/middleware/security_headers.py
git commit -m "feat: connection pool, liveness/readiness probes, solver threadpool, JSON logging, HSTS default"
```

---

## Task 6: Deployment artifacts

**Files:**
- Create: `deploy/nginx.conf`
- Create: `deploy/docker-compose.prod.yml`
- Create: `deploy/.env.production.example`
- Create: `deploy/backup.sh`
- Create: `deploy/README.md`

### 6a — nginx config

- [ ] **Step 1: Create nginx.conf**

```nginx
# deploy/nginx.conf
# TLS is terminated here. Set cert paths via NGINX_CERT / NGINX_KEY env vars,
# or mount them directly and edit the ssl_certificate lines below.

worker_processes auto;

events { worker_connections 1024; }

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    gzip          on;
    gzip_types    text/plain text/css application/javascript application/json;

    # Rate limit zone — 10 req/s per IP, burst 20
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

    # Redirect HTTP → HTTPS
    server {
        listen 80;
        server_name _;
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl;
        server_name _;

        ssl_certificate     /etc/nginx/certs/cert.pem;
        ssl_certificate_key /etc/nginx/certs/key.pem;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;
        ssl_session_cache   shared:SSL:10m;

        # Serve pre-built frontend static files
        root /usr/share/nginx/html;
        index index.html;

        # Frontend SPA — send all non-API paths to index.html
        location / {
            try_files $uri $uri/ /index.html;
            # Immutable cache for hashed assets (Vite produces content-hashed names)
            location ~* \.(js|css|woff2?|png|svg|ico)$ {
                expires 1y;
                add_header Cache-Control "public, immutable";
            }
        }

        # Backend API proxy
        location /api/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass         http://backend:8000;
            proxy_set_header   Host $host;
            proxy_set_header   X-Real-IP $remote_addr;
            proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header   X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;  # allow long algorithm runs to stream
            client_max_body_size 50m;
        }
    }
}
```

### 6b — production docker-compose

- [ ] **Step 2: Create docker-compose.prod.yml**

```yaml
# deploy/docker-compose.prod.yml
# Usage: docker compose -f deploy/docker-compose.prod.yml --env-file .env.production up -d
#
# Prerequisites:
#   - Build frontend: cd frontend && npm ci && npm run build
#   - Place TLS certs at deploy/certs/cert.pem and deploy/certs/key.pem
#   - Copy deploy/.env.production.example to .env.production and fill in values
#   - Create backup dir: mkdir -p /opt/justice/backups

services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: justice
    volumes:
      - /opt/justice/pgdata:/var/lib/postgresql/data
      - /opt/justice/backups:/backups
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d justice"]
      interval: 5s
      timeout: 5s
      retries: 10
    # Do NOT expose port 5432 externally — DB is internal-only

  backend:
    build:
      context: ../backend
      target: production
    restart: unless-stopped
    env_file: .env.production
    environment:
      LOG_DIR: /app/logs
      LOG_FORMAT: json
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - /opt/justice/logs:/app/logs
    command: >
      sh -c "alembic upgrade head &&
             uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8000/api/health/live || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5

  telegram-bot:
    build:
      context: ../backend
      target: production
    restart: unless-stopped
    env_file: .env.production
    environment:
      LOG_DIR: /app/logs
      LOG_FORMAT: json
    volumes:
      - /opt/justice/logs:/app/logs
    command: python -m bot.main
    depends_on:
      db:
        condition: service_healthy

  nginx:
    image: nginx:1.27-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
      - ../frontend/dist:/usr/share/nginx/html:ro
    depends_on:
      backend:
        condition: service_healthy
```

### 6c — production env template

- [ ] **Step 3: Create .env.production.example**

```bash
# deploy/.env.production.example
# Copy to .env.production and fill in every value.
# NEVER commit .env.production to git.

# ── Database ─────────────────────────────────────────────────────
# Use a strong random password. Rotate annually.
DATABASE_URL=postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@db:5432/justice
DB_ADMIN_URL=postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@db:5432/justice
DB_USER=justice
DB_PASSWORD=CHANGE_ME_STRONG_RANDOM_PASSWORD

# ── JWT ──────────────────────────────────────────────────────────
# Generate with: python3 -c "import secrets; print(secrets.token_hex(64))"
JWT_SECRET=CHANGE_ME_64_BYTE_HEX_SECRET
REFRESH_TOKEN_DAYS=30

# ── Cookies ──────────────────────────────────────────────────────
COOKIE_SECURE=true

# ── CORS — set to your internal hostname / IP ────────────────────
ALLOWED_ORIGINS=https://justice.internal

# ── Telegram ─────────────────────────────────────────────────────
# Rotate this token if it was ever committed to git
TELEGRAM_BOT_TOKEN=CHANGE_ME
TELEGRAM_BOT_USERNAME=your_bot_name

# ── Email (optional — leave blank to disable email notifications) ─
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=

# ── Logging ──────────────────────────────────────────────────────
LOG_FORMAT=json
# HSTS is set to 1 year by default in security_headers.py.
# Set to 0 only if nginx handles TLS and does not forward HTTPS headers.
HSTS_MAX_AGE=31536000
```

### 6d — backup script

- [ ] **Step 4: Create backup.sh**

```bash
#!/usr/bin/env bash
# deploy/backup.sh
# Run daily via cron. Writes compressed SQL dumps to BACKUP_DIR.
# Add to crontab: 0 2 * * * /opt/justice/deploy/backup.sh >> /opt/justice/logs/backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/justice/backups}"
CONTAINER="${CONTAINER:-$(docker ps --filter name=justice-db --format '{{.Names}}' | head -1)}"
DB_USER="${DB_USER:-justice}"
KEEP_DAYS="${KEEP_DAYS:-30}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTFILE="$BACKUP_DIR/justice_$TIMESTAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date -Iseconds)] Starting backup → $OUTFILE"
docker exec "$CONTAINER" pg_dump -U "$DB_USER" justice | gzip > "$OUTFILE"

SIZE=$(du -sh "$OUTFILE" | cut -f1)
echo "[$(date -Iseconds)] Backup complete — $SIZE"

# Prune old backups
find "$BACKUP_DIR" -name "justice_*.sql.gz" -mtime +"$KEEP_DAYS" -delete
echo "[$(date -Iseconds)] Pruned backups older than $KEEP_DAYS days"
```

```bash
chmod +x deploy/backup.sh
```

Add to system crontab:
```
0 2 * * * /opt/justice/deploy/backup.sh >> /opt/justice/logs/backup.log 2>&1
```

Test a restore:
```bash
# Restore test (run on a test DB, not production):
gunzip -c /opt/justice/backups/justice_YYYYMMDD_HHMMSS.sql.gz | \
  docker exec -i <db-container> psql -U justice -d justice_restore
```

### 6e — deployment README

- [ ] **Step 5: Create deploy/README.md**

```markdown
# Production Deployment Guide

## Prerequisites

- Docker + Docker Compose v2
- TLS certificates (self-signed for internal network: `openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout certs/key.pem -out certs/cert.pem`)
- Port 80 and 443 open on the host

## First-time setup

```bash
# 1. Generate TLS cert (internal network)
mkdir -p deploy/certs
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout deploy/certs/key.pem -out deploy/certs/cert.pem \
  -subj "/CN=justice.internal"

# 2. Configure environment
cp deploy/.env.production.example deploy/.env.production
# Edit .env.production — fill in DB_PASSWORD, JWT_SECRET, TELEGRAM_BOT_TOKEN, ALLOWED_ORIGINS

# 3. Build frontend
cd frontend && npm ci && npm run build && cd ..

# 4. Create data directories
sudo mkdir -p /opt/justice/pgdata /opt/justice/backups /opt/justice/logs

# 5. Start services
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production up -d

# 6. Schedule backups
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/justice/deploy/backup.sh >> /opt/justice/logs/backup.log 2>&1") | crontab -
```

## Updating

```bash
git pull
cd frontend && npm ci && npm run build && cd ..
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production up -d --build
```

## Restore from backup

```bash
# Stop backend to prevent writes during restore
docker compose -f deploy/docker-compose.prod.yml stop backend telegram-bot

# Restore
gunzip -c /opt/justice/backups/justice_YYYYMMDD_HHMMSS.sql.gz | \
  docker exec -i $(docker ps -qf name=justice-db) psql -U justice -d justice

# Restart
docker compose -f deploy/docker-compose.prod.yml start backend telegram-bot
```
```

- [ ] **Step 6: Commit all deployment artifacts**

```bash
git add deploy/
git commit -m "feat: production deployment — nginx, docker-compose.prod, backup script, env template, deploy guide"
```

---

## Self-review

**Spec coverage check:**

| Audit finding | Task |
|---|---|
| N+1 soldiers list | Task 2a |
| N+1 hierarchy nodes | Task 2b |
| N+1 register nodes | Task 2c |
| Missing FK indexes | Task 1 |
| Atomic lockout race condition | Task 3b |
| Filename not sanitised | Task 3c |
| Rate limit file download | Task 3d |
| Password complexity | Task 3e |
| Request body size limit | Task 3f |
| /ranks has no auth | Task 3a |
| CHECK constraints on dates | Task 4 |
| Connection pool too small | Task 5a |
| No liveness/readiness split | Task 5b |
| CP-SAT blocks event loop | Task 5c |
| No structured logging | Task 5d |
| HSTS disabled by default | Task 5e |
| No backup strategy | Task 6d |
| No production compose | Task 6b |
| No nginx/TLS | Task 6a |
| COOKIE_SECURE needs prod value | Task 6c |
| CORS contains personal hostnames | Task 6c |

All audit items are covered. No pagination on list endpoints is a larger structural change omitted intentionally — it requires frontend changes and is tracked separately.
