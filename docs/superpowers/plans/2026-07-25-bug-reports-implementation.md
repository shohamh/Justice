# Bug Report Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any authenticated user report a bug via a header icon that opens a modal
(screenshot + description + severity), submit it to the backend (which attaches
server-side context and mirrors to disk), and let admins triage reports in a new
System Settings tab.

**Architecture:** A portal-mounted trigger + modal in the frontend capture a
screenshot (`html-to-image`), the current route, and an in-memory navigation-history
ring buffer, then POST a single JSON body to a new `POST /bug-reports` endpoint. The
backend decodes the screenshot, queries the last 20 `AuditLog` rows for the reporter,
writes a JSON mirror to disk, and inserts a `bug_reports` row. Three admin-only
endpoints (list, JSON detail, screenshot, status update) back a new admin tab.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (dataclass-style models) + Alembic +
pytest/TestClient on the backend; React + TypeScript + react-router-dom +
@tanstack/react-query + vitest on the frontend; `html-to-image` is a new frontend
dependency.

**Design spec:** `docs/superpowers/specs/2026-07-25-bug-reports-design.md` — read
this first for the full rationale (portal mounting, error-handling matrix, retention
decision). This plan implements that spec verbatim except where noted inline.

## Global Constraints

- Screenshot is stored as raw `LargeBinary` bytes at rest (not base64 text), matching
  the codebase's existing upload pattern (`ExemptionRequestFile`, `GimelimAttachment`).
  It still travels over the wire as a base64 string inside the single JSON POST body
  (per the spec's `{description, severity, screenshot, route, nav_history}` shape) —
  the backend decodes it to bytes before storage.
- Screenshot cap: 5 MB decoded, must start with the PNG magic bytes
  (`\x89PNG\r\n\x1a\n`) or it is silently dropped (treated as "no screenshot").
- Description cap: 2000 chars, enforced in the Pydantic request schema.
- `reporter_id` is `UUID FK -> soldiers.id` (the only user table in this codebase is
  `Soldier`/`soldiers`).
- JSON mirror path resolves through `app.logging_config.LOG_DIR` (which itself
  respects the `LOG_DIR` env var, `/app/logs` in Docker) — never hardcode a
  repo-root-relative path.
- `screenshot` and `json_file_path` columns are nullable (capture/write can fail
  non-fatally per the spec's error-handling matrix).
- Admin endpoints are gated with `Depends(require_roles("admin"))`; the submit
  endpoint is gated with `Depends(require_password_changed)` (this codebase's
  standard "any authenticated user" dependency).
- No new pagination pattern — reuse the existing `offset`/`limit` `Query(...)`
  convention from `backend/app/routes/algorithm.py` and `notifications.py`.
- Hebrew UI, English code — there is only one locale file (`frontend/src/i18n/he.json`),
  no `en.json`. New user-facing strings go directly in Hebrew, either as literal
  strings (matching existing header icons like `aria-label="עזרה"`) or as new
  `he.json` keys where the surrounding code already uses `t(...)` (e.g. the admin tab
  bar).
- Retention: bug report rows and JSON mirror files are kept indefinitely; no cleanup
  job is in scope.

---

## File Structure

**Backend (new):**
- `backend/app/services/bug_reports.py` — JSON mirror + audit-snapshot + DB-insert orchestration (`write_bug_report`)
- `backend/app/routes/bug_reports.py` — `POST /bug-reports` + 4 admin endpoints (list, JSON detail, screenshot, status update)
- `backend/alembic/versions/<rev>_add_bug_reports.py` — new `bug_reports` table + 2 enum types
- `backend/tests/integration/test_bug_reports_service.py` — service-layer tests
- `backend/tests/integration/test_bug_reports_api.py` — route tests

**Backend (modified):**
- `backend/app/db/models.py` — add `BugReport` model
- `backend/app/main.py` — register the new router
- `backend/tests/conftest.py` — add `bug_reports` to `_ALL_DATA_TABLES` and `_AREA_MARKERS`

**Frontend (new):**
- `frontend/src/hooks/useNavigationHistory.tsx` — ring-buffer hook + `NavigationHistoryProvider` (`.tsx` because the provider needs JSX; the spec's `.ts` was written before the JSX requirement was worked out)
- `frontend/src/hooks/useNavigationHistory.test.tsx`
- `frontend/src/api/bugReports.ts` — typed fetch wrapper
- `frontend/src/components/BugReportModal.tsx`
- `frontend/src/components/BugReportModal.test.tsx`
- `frontend/src/components/BugReportTrigger.tsx` — portal-mounted trigger
- `frontend/src/components/BugReportTrigger.test.tsx`
- `frontend/src/pages/admin/BugReportsContent.tsx`
- `frontend/src/pages/admin/BugReportsContent.test.tsx`

**Frontend (modified):**
- `frontend/src/main.tsx` — wrap `<App />` in `<NavigationHistoryProvider>`
- `frontend/src/components/Layout.tsx` — mount `<BugReportTrigger />`
- `frontend/src/pages/admin/AdminSettingsPage.tsx` — 4th tab
- `frontend/src/i18n/he.json` — `nav.admin_bug_reports` key
- `frontend/package.json` — add `html-to-image`

---

### Task 1: `BugReport` model, migration, and `bug_reports` service

**Files:**
- Modify: `backend/app/db/models.py` (append after the `ForcedCallup` class, end of file)
- Create: `backend/alembic/versions/b7e4a19f6c3d_add_bug_reports.py`
- Modify: `backend/tests/conftest.py:131` (`_ALL_DATA_TABLES`) and `:100` (`_AREA_MARKERS`)
- Create: `backend/app/services/bug_reports.py`
- Test: `backend/tests/integration/test_bug_reports_service.py`

**Interfaces:**
- Produces: `app.db.models.BugReport` (columns: `id`, `reporter_id`, `description`,
  `severity`, `route`, `status`, `screenshot`, `nav_history`, `audit_snapshot`,
  `user_snapshot`, `json_file_path`, `created_at`, `updated_at`)
- Produces: `app.services.bug_reports.write_bug_report(session, *, reporter: Soldier,
  description: str, severity: str, screenshot: bytes | None, route: str,
  nav_history: list[dict]) -> BugReportWriteResult` where
  `BugReportWriteResult(persisted_to_db: bool, json_file_path: str | None)`
- Produces: `app.services.bug_reports.BugReportWriteError` (raised only when both the
  JSON write and the DB insert fail)
- Consumes: `app.logging_config.LOG_DIR`, `app.db.models.AuditLog`, `tests.helpers.create_soldier`

- [ ] **Step 1: Write the failing service tests**

Create `backend/tests/integration/test_bug_reports_service.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.models import AuditLog, BugReport
from app.services import bug_reports as svc
from tests.helpers import create_soldier


def test_write_bug_report_persists_row_and_json_mirror(admin_session: Session, tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path)
    reporter = create_soldier(admin_session, personal_number="bugsvc001")

    result = svc.write_bug_report(
        admin_session,
        reporter=reporter,
        description="the button does nothing",
        severity="medium",
        screenshot=None,
        route="/duty",
        nav_history=[
            {"path": "/", "timestamp": "2026-07-25T10:00:00Z"},
            {"path": "/duty", "timestamp": "2026-07-25T10:00:05Z"},
        ],
    )
    admin_session.commit()

    assert result.persisted_to_db is True
    assert result.json_file_path is not None

    row = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one()
    assert row.description == "the button does nothing"
    assert row.severity == "medium"
    assert row.status == "open"
    assert row.route == "/duty"
    assert row.screenshot is None
    assert row.json_file_path == result.json_file_path

    mirrored = json.loads(Path(result.json_file_path).read_text())
    assert mirrored["description"] == "the button does nothing"
    assert mirrored["user_snapshot"]["id"] == str(reporter.id)


def test_write_bug_report_includes_recent_audit_log_entries(admin_session: Session, tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path)
    reporter = create_soldier(admin_session, personal_number="bugsvc002")
    admin_session.add(AuditLog(action="login", entity_type="soldier", actor_id=reporter.id, entity_id=reporter.id))
    admin_session.commit()

    svc.write_bug_report(
        admin_session, reporter=reporter, description="x", severity="low", screenshot=None, route="/", nav_history=[],
    )
    admin_session.commit()

    row = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one()
    assert len(row.audit_snapshot) == 1
    assert row.audit_snapshot[0]["action"] == "login"


def test_write_bug_report_stores_screenshot_bytes(admin_session: Session, tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path)
    reporter = create_soldier(admin_session, personal_number="bugsvc003")

    svc.write_bug_report(
        admin_session, reporter=reporter, description="x", severity="low",
        screenshot=b"\x89PNG\r\n\x1a\nrest-of-file", route="/", nav_history=[],
    )
    admin_session.commit()

    row = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one()
    assert row.screenshot == b"\x89PNG\r\n\x1a\nrest-of-file"


def test_write_bug_report_returns_success_when_only_db_fails(admin_session: Session, tmp_path, monkeypatch):
    # JSON mirror succeeds (LOG_DIR is a valid tmp dir); the DB insert fails because
    # this reporter was never actually persisted, so the FK constraint violates on
    # flush. Per the spec, this must NOT raise — the JSON file is durable, so the
    # write is still a success from the caller's perspective.
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path)
    from app.db.models import Soldier
    import uuid
    phantom_reporter = Soldier(personal_number="phantom2", full_name="Phantom2", password_hash="x", id=uuid.uuid4())

    result = svc.write_bug_report(
        admin_session, reporter=phantom_reporter, description="x", severity="low",
        screenshot=None, route="/", nav_history=[],
    )

    assert result.persisted_to_db is False
    assert result.json_file_path is not None
    assert Path(result.json_file_path).exists()


def test_write_bug_report_raises_when_json_write_fails_and_db_fails(admin_session: Session, tmp_path, monkeypatch):
    # Point LOG_DIR at a file (not a directory) so mkdir()/write_text() raise OSError,
    # and break the DB insert by handing it a reporter that was never committed
    # (so the FK constraint fails on flush).
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path / "not-a-dir")
    (tmp_path / "not-a-dir").write_text("blocking file")

    from app.db.models import Soldier
    import uuid
    phantom_reporter = Soldier(
        personal_number="phantom", full_name="Phantom", password_hash="x", id=uuid.uuid4(),
    )

    with pytest.raises(svc.BugReportWriteError):
        svc.write_bug_report(
            admin_session, reporter=phantom_reporter, description="x", severity="low",
            screenshot=None, route="/", nav_history=[],
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/integration/test_bug_reports_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.bug_reports'` (and `ImportError: cannot import name 'BugReport'`)

- [ ] **Step 3: Add the `BugReport` model**

Append to the end of `backend/app/db/models.py` (after the `ForcedCallup` class; no new imports needed — `Enum`, `Text`, `UUID`, `JSONB`, `text`, `sa` are already imported at the top of the file):

```python


class BugReport(Base):
    __tablename__ = "bug_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", name="bug_report_severity")
    )
    route: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Enum("open", "in_progress", "resolved", name="bug_report_status"),
        server_default="open", default="open",
    )
    screenshot: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True, default=None)
    nav_history: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True, default=None)
    audit_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True, default=None)
    user_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    json_file_path: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 4: Write the Alembic migration**

First confirm the current head (it may have moved since this plan was written):

Run: `cd backend && alembic heads`
Expected: `71e217f7c372 (head)` — if different, use the actual head as `down_revision` below.

Create `backend/alembic/versions/b7e4a19f6c3d_add_bug_reports.py`:

```python
"""Add bug_reports table

Revision ID: b7e4a19f6c3d
Revises: 71e217f7c372
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "b7e4a19f6c3d"
down_revision = "71e217f7c372"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE bug_report_severity AS ENUM ('low', 'medium', 'high')")
    op.execute("CREATE TYPE bug_report_status AS ENUM ('open', 'in_progress', 'resolved')")
    op.create_table(
        "bug_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("reporter_id", UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("severity", sa.Enum("low", "medium", "high", name="bug_report_severity", create_type=False), nullable=False),
        sa.Column("route", sa.Text, nullable=False),
        sa.Column("status", sa.Enum("open", "in_progress", "resolved", name="bug_report_status", create_type=False), server_default="open", nullable=False),
        sa.Column("screenshot", sa.LargeBinary, nullable=True),
        sa.Column("nav_history", JSONB, nullable=True),
        sa.Column("audit_snapshot", JSONB, nullable=True),
        sa.Column("user_snapshot", JSONB, nullable=True),
        sa.Column("json_file_path", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bug_reports")
    op.execute("DROP TYPE bug_report_severity")
    op.execute("DROP TYPE bug_report_status")
```

- [ ] **Step 5: Run the migration**

Run: `cd backend && alembic upgrade head`
Expected: output ending with `Running upgrade 71e217f7c372 -> b7e4a19f6c3d, Add bug_reports table`

- [ ] **Step 6: Register the table in test infra**

In `backend/tests/conftest.py`, add to `_ALL_DATA_TABLES` (right after `"audit_log",` at line 131 — must come before `"soldiers"` since it FKs to it):

```python
_ALL_DATA_TABLES = [
    "audit_log",
    "bug_reports",
    "duty_day_overrides",
```

And add to `_AREA_MARKERS`, right after `"test_logging_config": "misc",`:

```python
    "test_logging_config": "misc",
    "test_bug_reports_service": "misc",
    "test_bug_reports_api": "misc",
}
```

- [ ] **Step 7: Implement the service**

Create `backend/app/services/bug_reports.py`:

```python
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, BugReport, Soldier
from app.logging_config import LOG_DIR

logger = logging.getLogger(__name__)


class BugReportWriteError(Exception):
    """Raised only when both the JSON mirror and the DB insert fail."""


@dataclass
class BugReportWriteResult:
    persisted_to_db: bool
    json_file_path: str | None


def _json_default(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {value!r}")


def _audit_snapshot(session: Session, reporter_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        select(AuditLog)
        .where(AuditLog.actor_id == reporter_id)
        .order_by(AuditLog.created_at.desc())
        .limit(20)
    ).scalars().all()
    return [
        {
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id) if row.entity_id else None,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def _write_json_mirror(report_id: uuid.UUID, created_at: datetime, payload: dict[str, Any]) -> str | None:
    json_dir = LOG_DIR / "bug_reports"
    try:
        json_dir.mkdir(parents=True, exist_ok=True)
        file_path = json_dir / f"{report_id}_{created_at.strftime('%Y%m%dT%H%M%S')}.json"
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
        return str(file_path)
    except OSError:
        logger.exception("bug_report_json_write_failed", extra={"report_id": str(report_id)})
        return None


def write_bug_report(
    session: Session,
    *,
    reporter: Soldier,
    description: str,
    severity: str,
    screenshot: bytes | None,
    route: str,
    nav_history: list[dict[str, Any]],
) -> BugReportWriteResult:
    report_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)

    audit_snapshot = _audit_snapshot(session, reporter.id)
    user_snapshot = {
        "id": str(reporter.id),
        "full_name": reporter.full_name,
        "rank": reporter.rank,
        "role": reporter.role,
        "personal_number": reporter.personal_number,
    }

    json_payload = {
        "id": str(report_id),
        "reporter_id": str(reporter.id),
        "description": description,
        "severity": severity,
        "route": route,
        "nav_history": nav_history,
        "audit_snapshot": audit_snapshot,
        "user_snapshot": user_snapshot,
        "has_screenshot": screenshot is not None,
        "created_at": created_at.isoformat(),
    }
    json_file_path = _write_json_mirror(report_id, created_at, json_payload)

    persisted_to_db = True
    try:
        report = BugReport(
            id=report_id,
            reporter_id=reporter.id,
            description=description,
            severity=severity,
            route=route,
            status="open",
            screenshot=screenshot,
            nav_history=nav_history,
            audit_snapshot=audit_snapshot,
            user_snapshot=user_snapshot,
            json_file_path=json_file_path,
        )
        session.add(report)
        session.flush()
    except Exception:
        session.rollback()
        logger.exception("bug_report_db_insert_failed", extra={"report_id": str(report_id)})
        persisted_to_db = False

    if not persisted_to_db and json_file_path is None:
        raise BugReportWriteError("both_json_and_db_write_failed")

    return BugReportWriteResult(persisted_to_db=persisted_to_db, json_file_path=json_file_path)
```

- [ ] **Step 8: Run the tests again to verify they pass**

Run: `pytest backend/tests/integration/test_bug_reports_service.py -v`
Expected: 5 passed

- [ ] **Step 9: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/b7e4a19f6c3d_add_bug_reports.py backend/app/services/bug_reports.py backend/tests/conftest.py backend/tests/integration/test_bug_reports_service.py
git commit -m "feat: add BugReport model, migration, and write_bug_report service"
```

---

### Task 2: `POST /bug-reports` route

**Files:**
- Create: `backend/app/routes/bug_reports.py`
- Modify: `backend/app/main.py` (add import + `include_router`, at the end of each list)
- Test: `backend/tests/integration/test_bug_reports_api.py`

**Interfaces:**
- Consumes: `app.services.bug_reports.write_bug_report`, `.BugReportWriteError` (Task 1); `app.auth.deps.require_password_changed`
- Produces: `router` (FastAPI `APIRouter`) mounted at `/api` — `POST /bug-reports` returning `{"status": "ok"}` on success

- [ ] **Step 1: Write the failing route tests**

Create `backend/tests/integration/test_bug_reports_api.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import BugReport
from app.services import bug_reports as svc
from tests.helpers import auth_headers, create_soldier

# Canonical 1x1 transparent PNG. The magic-byte prefix ("iVBORw0KGgo" -> the PNG
# signature) is what the backend actually validates.
_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="


@pytest.fixture(autouse=True)
def _isolate_log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path)


def test_submit_bug_report_creates_row(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi001")

    resp = client.post(
        "/api/bug-reports",
        json={
            "description": "the calendar is blank",
            "severity": "high",
            "screenshot": _TINY_PNG_B64,
            "route": "/calendar",
            "nav_history": [{"path": "/", "timestamp": "2026-07-25T10:00:00Z"}],
        },
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 201
    assert resp.json() == {"status": "ok"}

    row = admin_session.query(BugReport).filter_by(reporter_id=soldier.id).one()
    assert row.severity == "high"
    assert row.screenshot is not None


def test_submit_bug_report_without_screenshot(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi002")

    resp = client.post(
        "/api/bug-reports",
        json={"description": "no screenshot captured", "severity": "low", "route": "/"},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 201
    row = admin_session.query(BugReport).filter_by(reporter_id=soldier.id).one()
    assert row.screenshot is None


def test_submit_bug_report_requires_auth(client: TestClient):
    resp = client.post("/api/bug-reports", json={"description": "x", "severity": "low", "route": "/"})
    assert resp.status_code == 401


def test_submit_bug_report_rejects_bad_severity(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi003")
    resp = client.post(
        "/api/bug-reports",
        json={"description": "x", "severity": "urgent", "route": "/"},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 422


def test_submit_bug_report_rejects_empty_description(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi004")
    resp = client.post(
        "/api/bug-reports",
        json={"description": "", "severity": "low", "route": "/"},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 422


def test_submit_bug_report_drops_invalid_screenshot_data(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi005")
    resp = client.post(
        "/api/bug-reports",
        json={"description": "x", "severity": "low", "route": "/", "screenshot": "not-base64-png-data!!!"},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 201
    row = admin_session.query(BugReport).filter_by(reporter_id=soldier.id).one()
    assert row.screenshot is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/integration/test_bug_reports_api.py -v`
Expected: FAIL — `404 Not Found` (route not registered) on every test

- [ ] **Step 3: Implement the route**

Create `backend/app/routes/bug_reports.py`:

```python
from __future__ import annotations

import base64
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.db.models import Soldier
from app.db.session import get_session
from app.services import bug_reports as svc

router = APIRouter(tags=["bug_reports"])

_MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024  # 5 MB
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class NavHistoryEntry(BaseModel):
    path: str
    timestamp: str


class BugReportSubmitBody(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    severity: Literal["low", "medium", "high"]
    screenshot: str | None = None
    route: str
    nav_history: list[NavHistoryEntry] = Field(default_factory=list)


def _decode_screenshot(b64: str) -> bytes | None:
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception:
        return None
    if len(data) > _MAX_SCREENSHOT_BYTES or not data.startswith(_PNG_MAGIC):
        return None
    return data


@router.post("/bug-reports", status_code=status.HTTP_201_CREATED)
def submit_bug_report(
    body: BugReportSubmitBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    screenshot_bytes = _decode_screenshot(body.screenshot) if body.screenshot else None
    try:
        svc.write_bug_report(
            session,
            reporter=user,
            description=body.description,
            severity=body.severity,
            screenshot=screenshot_bytes,
            route=body.route,
            nav_history=[entry.model_dump() for entry in body.nav_history],
        )
    except svc.BugReportWriteError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="bug_report_write_failed") from exc
    session.commit()
    return {"status": "ok"}
```

- [ ] **Step 4: Wire the router into `main.py`**

In `backend/app/main.py`, add to the end of the import block (after `from app.routes import potential as potential_routes`):

```python
from app.routes import bug_reports as bug_report_routes
```

And add to the end of the `include_router` block (after `app.include_router(potential_routes.router, prefix="/api")`):

```python
    app.include_router(bug_report_routes.router, prefix="/api")
```

- [ ] **Step 5: Run the tests again to verify they pass**

Run: `pytest backend/tests/integration/test_bug_reports_api.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/bug_reports.py backend/app/main.py backend/tests/integration/test_bug_reports_api.py
git commit -m "feat: add POST /bug-reports endpoint"
```

---

### Task 3: Admin bug-report routes (list, JSON detail, screenshot, status update)

**Files:**
- Modify: `backend/app/routes/bug_reports.py`
- Test: `backend/tests/integration/test_bug_reports_api.py` (append)

**Interfaces:**
- Consumes: `app.auth.deps.require_roles`
- Produces: `GET /admin/bug-reports` (paginated, filterable), `GET
  /admin/bug-reports/{id}/json`, `GET /admin/bug-reports/{id}/screenshot`, `PATCH
  /admin/bug-reports/{id}`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/integration/test_bug_reports_api.py`:

```python
def _submit(client: TestClient, reporter, **overrides):
    body = {"description": "x", "severity": "low", "route": "/"}
    body.update(overrides)
    resp = client.post("/api/bug-reports", json=body, headers=auth_headers(reporter))
    assert resp.status_code == 201
    return resp


def test_list_bug_reports_requires_admin(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi010")
    resp = client.get("/api/admin/bug-reports", headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_list_bug_reports_filters_by_severity_and_paginates(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi011", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi012")
    for sev in ("low", "medium", "high"):
        _submit(client, reporter, description=f"bug-{sev}", severity=sev)

    resp = client.get("/api/admin/bug-reports", params={"severity": "high"}, headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["severity"] == "high"

    resp = client.get("/api/admin/bug-reports", params={"limit": 1, "offset": 0}, headers=auth_headers(admin))
    assert len(resp.json()["items"]) == 1
    assert resp.json()["total"] == 3


def test_update_bug_report_status_persists(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi013", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi014")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.patch(f"/api/admin/bug-reports/{report_id}", json={"status": "resolved"}, headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"

    admin_session.expire_all()
    assert admin_session.get(BugReport, report_id).status == "resolved"


def test_update_bug_report_status_requires_admin(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugapi015")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.patch(f"/api/admin/bug-reports/{report_id}", json={"status": "resolved"}, headers=auth_headers(reporter))
    assert resp.status_code == 403


def test_get_bug_report_json_returns_mirrored_file(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi016", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi017")
    _submit(client, reporter, description="mirrored description")
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.get(f"/api/admin/bug-reports/{report_id}/json", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["description"] == "mirrored description"


def test_get_bug_report_json_requires_admin(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugapi018")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.get(f"/api/admin/bug-reports/{report_id}/json", headers=auth_headers(reporter))
    assert resp.status_code == 403


def test_get_bug_report_screenshot_returns_png_bytes(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi019", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi020")
    _submit(client, reporter, screenshot=_TINY_PNG_B64)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.get(f"/api/admin/bug-reports/{report_id}/screenshot", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_get_bug_report_screenshot_404_when_none_captured(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi021", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi022")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.get(f"/api/admin/bug-reports/{report_id}/screenshot", headers=auth_headers(admin))
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/integration/test_bug_reports_api.py -v`
Expected: FAIL — `404 Not Found` on the new admin-route tests

- [ ] **Step 3: Implement the admin endpoints**

In `backend/app/routes/bug_reports.py`, replace the imports block at the top of the file:

```python
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed, require_roles
from app.db.models import BugReport, Soldier
from app.db.session import get_session
from app.services import bug_reports as svc
```

Then append to the end of the file (after `submit_bug_report`):

```python


class BugReportSummaryOut(BaseModel):
    id: uuid.UUID
    reporter_id: uuid.UUID
    description: str
    severity: str
    status: str
    route: str
    nav_history: list[dict] | None
    audit_snapshot: list[dict] | None
    user_snapshot: dict | None
    has_screenshot: bool
    created_at: datetime
    updated_at: datetime


class PaginatedBugReports(BaseModel):
    items: list[BugReportSummaryOut]
    total: int


class UpdateBugReportStatusBody(BaseModel):
    status: Literal["open", "in_progress", "resolved"]


def _summary_out(report: BugReport) -> BugReportSummaryOut:
    return BugReportSummaryOut(
        id=report.id,
        reporter_id=report.reporter_id,
        description=report.description,
        severity=report.severity,
        status=report.status,
        route=report.route,
        nav_history=report.nav_history,
        audit_snapshot=report.audit_snapshot,
        user_snapshot=report.user_snapshot,
        has_screenshot=report.screenshot is not None,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.get("/admin/bug-reports", response_model=PaginatedBugReports)
def list_bug_reports(
    session: Session = Depends(get_session),
    _admin: Soldier = Depends(require_roles("admin")),
    severity: Literal["low", "medium", "high"] | None = None,
    status_filter: Literal["open", "in_progress", "resolved"] | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaginatedBugReports:
    query = select(BugReport)
    count_query = select(func.count()).select_from(BugReport)
    if severity is not None:
        query = query.where(BugReport.severity == severity)
        count_query = count_query.where(BugReport.severity == severity)
    if status_filter is not None:
        query = query.where(BugReport.status == status_filter)
        count_query = count_query.where(BugReport.status == status_filter)

    total = session.execute(count_query).scalar_one()
    items = session.execute(
        query.order_by(BugReport.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return PaginatedBugReports(items=[_summary_out(r) for r in items], total=total)


@router.get("/admin/bug-reports/{report_id}/json")
def get_bug_report_json(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    _admin: Soldier = Depends(require_roles("admin")),
) -> Response:
    report = session.get(BugReport, report_id)
    if report is None or not report.json_file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bug_report_json_not_found")
    path = Path(report.json_file_path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bug_report_json_not_found")
    return Response(content=path.read_text(), media_type="application/json")


@router.get("/admin/bug-reports/{report_id}/screenshot")
def get_bug_report_screenshot(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    _admin: Soldier = Depends(require_roles("admin")),
) -> Response:
    report = session.get(BugReport, report_id)
    if report is None or report.screenshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bug_report_screenshot_not_found")
    return Response(content=report.screenshot, media_type="image/png")


@router.patch("/admin/bug-reports/{report_id}", response_model=BugReportSummaryOut)
def update_bug_report_status(
    report_id: uuid.UUID,
    body: UpdateBugReportStatusBody,
    session: Session = Depends(get_session),
    _admin: Soldier = Depends(require_roles("admin")),
) -> BugReportSummaryOut:
    report = session.get(BugReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bug_report_not_found")
    report.status = body.status
    report.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(report)
    return _summary_out(report)
```

- [ ] **Step 4: Run the tests again to verify they pass**

Run: `pytest backend/tests/integration/test_bug_reports_api.py -v`
Expected: 14 passed

- [ ] **Step 5: Run the full backend `misc` slice**

Run: `pytest -m misc -q`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/bug_reports.py backend/tests/integration/test_bug_reports_api.py
git commit -m "feat: add admin bug-report list/json/screenshot/status endpoints"
```

---

### Task 4: `useNavigationHistory` ring buffer + provider

**Files:**
- Create: `frontend/src/hooks/useNavigationHistory.tsx`
- Test: `frontend/src/hooks/useNavigationHistory.test.tsx`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Produces: `NavigationHistoryProvider({ children })`, `useNavigationHistory(): NavHistoryEntry[]` where `NavHistoryEntry = { path: string; timestamp: string }`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/useNavigationHistory.test.tsx`:

```tsx
import { describe, expect, test } from "vitest";
import { useEffect } from "react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { act, render, screen } from "@testing-library/react";
import { NavigationHistoryProvider, useNavigationHistory } from "./useNavigationHistory";

function Probe() {
  const history = useNavigationHistory();
  return <div data-testid="history">{JSON.stringify(history.map((h) => h.path))}</div>;
}

function NavCapture({ navigateRef }: { navigateRef: { current: ((path: string) => void) | null } }) {
  const navigate = useNavigate();
  useEffect(() => { navigateRef.current = navigate; }, [navigate]);
  return <Probe />;
}

describe("useNavigationHistory", () => {
  test("records the initial route", () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <NavigationHistoryProvider>
          <Probe />
        </NavigationHistoryProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("history").textContent).toBe(JSON.stringify(["/duty"]));
  });

  test("caps the ring buffer at 15 entries, keeping the most recent", () => {
    const navigateRef: { current: ((path: string) => void) | null } = { current: null };
    render(
      <MemoryRouter initialEntries={["/start"]}>
        <NavigationHistoryProvider>
          <NavCapture navigateRef={navigateRef} />
        </NavigationHistoryProvider>
      </MemoryRouter>,
    );

    act(() => {
      for (let i = 0; i < 20; i++) navigateRef.current!(`/page-${i}`);
    });

    const recorded = JSON.parse(screen.getByTestId("history").textContent!);
    expect(recorded).toHaveLength(15);
    expect(recorded[0]).toBe("/page-5");
    expect(recorded[14]).toBe("/page-19");
  });

  test("throws when used outside the provider", () => {
    function Bare() {
      useNavigationHistory();
      return null;
    }
    expect(() => render(<Bare />)).toThrow("useNavigationHistory must be used inside NavigationHistoryProvider");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- useNavigationHistory`
Expected: FAIL — cannot find module `./useNavigationHistory`

- [ ] **Step 3: Implement the hook and provider**

Create `frontend/src/hooks/useNavigationHistory.tsx`:

```tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

export interface NavHistoryEntry {
  path: string;
  timestamp: string;
}

const MAX_ENTRIES = 15;

interface NavigationHistoryContextValue {
  history: NavHistoryEntry[];
}

const NavigationHistoryContext = createContext<NavigationHistoryContextValue | null>(null);

export function NavigationHistoryProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [history, setHistory] = useState<NavHistoryEntry[]>([]);

  useEffect(() => {
    setHistory((prev) => {
      const entry: NavHistoryEntry = { path: location.pathname, timestamp: new Date().toISOString() };
      const next = [...prev, entry];
      return next.length > MAX_ENTRIES ? next.slice(next.length - MAX_ENTRIES) : next;
    });
  }, [location.pathname]);

  return (
    <NavigationHistoryContext.Provider value={{ history }}>
      {children}
    </NavigationHistoryContext.Provider>
  );
}

export function useNavigationHistory(): NavHistoryEntry[] {
  const ctx = useContext(NavigationHistoryContext);
  if (!ctx) throw new Error("useNavigationHistory must be used inside NavigationHistoryProvider");
  return ctx.history;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- useNavigationHistory`
Expected: 3 passed

- [ ] **Step 5: Wire the provider into `main.tsx`**

In `frontend/src/main.tsx`, add the import:

```tsx
import { NavigationHistoryProvider } from "./hooks/useNavigationHistory";
```

And wrap `<App />` (must be inside `<BrowserRouter>` since the hook uses `useLocation`):

```tsx
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <NavigationHistoryProvider>
          <AlgorithmSeenProvider>
            <App />
          </AlgorithmSeenProvider>
        </NavigationHistoryProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useNavigationHistory.tsx frontend/src/hooks/useNavigationHistory.test.tsx frontend/src/main.tsx
git commit -m "feat: add navigation-history ring buffer for bug reports"
```

---

### Task 5: `api/bugReports.ts` typed wrapper

**Files:**
- Create: `frontend/src/api/bugReports.ts`

**Interfaces:**
- Consumes: `api` from `./client`
- Produces: `submitBugReport`, `listBugReports`, `getBugReportJson`, `fetchBugReportScreenshot`, `updateBugReportStatus`, and types `BugReportSubmitPayload`, `BugReportSummary`, `PaginatedBugReports`, `BugReportFilters`

- [ ] **Step 1: Implement the wrapper**

Create `frontend/src/api/bugReports.ts`:

```ts
import { api } from "./client";
import type { NavHistoryEntry } from "../hooks/useNavigationHistory";

export type BugReportSeverity = "low" | "medium" | "high";
export type BugReportStatus = "open" | "in_progress" | "resolved";

export interface BugReportSubmitPayload {
  description: string;
  severity: BugReportSeverity;
  screenshot: string | null;
  route: string;
  nav_history: NavHistoryEntry[];
}

export async function submitBugReport(payload: BugReportSubmitPayload): Promise<void> {
  await api.post("/bug-reports", payload);
}

export interface BugReportSummary {
  id: string;
  reporter_id: string;
  description: string;
  severity: BugReportSeverity;
  status: BugReportStatus;
  route: string;
  nav_history: NavHistoryEntry[] | null;
  audit_snapshot: Record<string, unknown>[] | null;
  user_snapshot: Record<string, unknown> | null;
  has_screenshot: boolean;
  created_at: string;
  updated_at: string;
}

export interface PaginatedBugReports {
  items: BugReportSummary[];
  total: number;
}

export interface BugReportFilters {
  severity?: BugReportSeverity;
  status?: BugReportStatus;
  offset?: number;
  limit?: number;
}

export async function listBugReports(filters: BugReportFilters): Promise<PaginatedBugReports> {
  return (await api.get<PaginatedBugReports>("/admin/bug-reports", { params: filters })).data;
}

export async function getBugReportJson(id: string): Promise<unknown> {
  return (await api.get(`/admin/bug-reports/${id}/json`)).data;
}

export async function fetchBugReportScreenshot(id: string): Promise<Blob> {
  return (await api.get(`/admin/bug-reports/${id}/screenshot`, { responseType: "blob" })).data;
}

export async function updateBugReportStatus(id: string, status: BugReportStatus): Promise<BugReportSummary> {
  return (await api.patch<BugReportSummary>(`/admin/bug-reports/${id}`, { status })).data;
}
```

- [ ] **Step 2: Typecheck**

Run: `npm run typecheck`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/bugReports.ts
git commit -m "feat: add bugReports typed API wrapper"
```

---

### Task 6: `BugReportModal` + `html-to-image` dependency

**Files:**
- Modify: `frontend/package.json` (add `html-to-image`)
- Create: `frontend/src/components/BugReportModal.tsx`
- Test: `frontend/src/components/BugReportModal.test.tsx`

**Interfaces:**
- Consumes: `submitBugReport` (Task 5), `useNavigationHistory` (Task 4), `useLocation` from `react-router-dom`, `translateApiError`
- Produces: `BugReportModal({ onClose: () => void })`

- [ ] **Step 1: Add the `html-to-image` dependency**

In `frontend/package.json`, add to `dependencies` (alphabetically, after `"fuse.js": "^7.4.2",`):

```json
    "fuse.js": "^7.4.2",
    "html-to-image": "^1.11.11",
    "i18next": "^23.10.0",
```

Run: `cd frontend && npm install`
Expected: `html-to-image` added to `package-lock.json`

- [ ] **Step 2: Write the failing test**

Create `frontend/src/components/BugReportModal.test.tsx`:

```tsx
import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import BugReportModal from "./BugReportModal";
import { submitBugReport } from "../api/bugReports";

vi.mock("html-to-image", () => ({
  toPng: vi.fn().mockResolvedValue("data:image/png;base64,AAA"),
}));
vi.mock("../api/bugReports", () => ({
  submitBugReport: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("../hooks/useNavigationHistory", () => ({
  useNavigationHistory: () => [{ path: "/", timestamp: "2026-07-25T10:00:00Z" }],
}));

describe("BugReportModal", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  test("submits the selected severity, description, and route", async () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal onClose={vi.fn()} />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByTestId("bug-report-description"), { target: { value: "the button breaks" } });
    fireEvent.click(screen.getByTestId("bug-report-severity-high"));
    fireEvent.click(screen.getByTestId("bug-report-submit"));

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "high", description: "the button breaks", route: "/duty" }),
    ));
  });

  test("defaults to medium severity when none is explicitly chosen", async () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal onClose={vi.fn()} />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByTestId("bug-report-description"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("bug-report-submit"));

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "medium" }),
    ));
  });

  test("disables submit until a description is entered", () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("bug-report-submit")).toBeDisabled();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- BugReportModal`
Expected: FAIL — cannot find module `./BugReportModal`

- [ ] **Step 4: Implement the modal**

Create `frontend/src/components/BugReportModal.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toPng } from "html-to-image";
import { translateApiError } from "../utils/translateApiError";
import { submitBugReport } from "../api/bugReports";
import { useNavigationHistory } from "../hooks/useNavigationHistory";

type Severity = "low" | "medium" | "high";

const SEVERITIES: { value: Severity; label: string }[] = [
  { value: "low", label: "נמוכה" },
  { value: "medium", label: "בינונית" },
  { value: "high", label: "גבוהה" },
];

export default function BugReportModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const location = useLocation();
  const navHistory = useNavigationHistory();
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(true);
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<Severity>("medium");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [succeeded, setSucceeded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    toPng(document.body)
      .then((dataUrl) => { if (!cancelled) setScreenshot(dataUrl); })
      .catch(() => { /* non-fatal: submission proceeds without a screenshot */ })
      .finally(() => { if (!cancelled) setCapturing(false); });
    return () => { cancelled = true; };
  }, []);

  async function handleSubmit() {
    if (!description.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitBugReport({
        description: description.trim(),
        severity,
        screenshot: screenshot ? (screenshot.split(",")[1] ?? null) : null,
        route: location.pathname,
        nav_history: navHistory,
      });
      setSucceeded(true);
      setTimeout(onClose, 1200);
    } catch (err: unknown) {
      setError(translateApiError(err, t, "שגיאה בשליחת הדיווח"));
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-[110]"
      onClick={onClose}
      data-testid="bug-report-modal-overlay"
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-3">
          <h3 className="text-lg font-semibold">מצאתי באג</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700" data-testid="bug-report-modal-close">✕</button>
        </div>

        {succeeded ? (
          <p className="text-sm text-green-600" data-testid="bug-report-success">הדיווח נשלח בהצלחה, תודה!</p>
        ) : (
          <>
            <div className="mb-3">
              {capturing ? (
                <p className="text-xs text-gray-500">מצלם צילום מסך...</p>
              ) : screenshot ? (
                <img src={screenshot} alt="" className="w-full rounded border dark:border-gray-600" />
              ) : (
                <p className="text-xs text-gray-500">לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו</p>
              )}
            </div>
            <textarea
              className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
              placeholder="מה קרה?"
              data-testid="bug-report-description"
            />
            <div className="flex gap-2 mt-3" data-testid="bug-report-severity-picker">
              {SEVERITIES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  onClick={() => setSeverity(s.value)}
                  className={`flex-1 px-2 py-1 text-xs rounded border ${
                    severity === s.value
                      ? "bg-indigo-600 text-white border-indigo-600"
                      : "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300"
                  }`}
                  data-testid={`bug-report-severity-${s.value}`}
                >
                  {s.label}
                </button>
              ))}
            </div>
            {error && <p className="text-red-500 text-xs mt-2">{error}</p>}
            <div className="flex justify-end gap-2 mt-4">
              <button type="button" onClick={onClose} disabled={submitting} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50">
                ביטול
              </button>
              <button
                type="button"
                onClick={() => { void handleSubmit(); }}
                disabled={submitting || !description.trim()}
                className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
                data-testid="bug-report-submit"
              >
                {submitting ? "שולח..." : "שליחה"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- BugReportModal`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/BugReportModal.tsx frontend/src/components/BugReportModal.test.tsx
git commit -m "feat: add BugReportModal with screenshot capture and severity picker"
```

---

### Task 7: `BugReportTrigger` (portal) + mount in `Layout.tsx`

**Files:**
- Create: `frontend/src/components/BugReportTrigger.tsx`
- Test: `frontend/src/components/BugReportTrigger.test.tsx`
- Modify: `frontend/src/components/Layout.tsx`

**Interfaces:**
- Consumes: `BugReportModal` (Task 6)
- Produces: `BugReportTrigger()` (no props) — portals a fixed-position header-style icon + its modal into `document.body`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/BugReportTrigger.test.tsx`:

```tsx
import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import BugReportTrigger from "./BugReportTrigger";

vi.mock("html-to-image", () => ({ toPng: vi.fn().mockResolvedValue("data:image/png;base64,AAA") }));
vi.mock("../hooks/useNavigationHistory", () => ({ useNavigationHistory: () => [] }));

describe("BugReportTrigger", () => {
  test("opens the bug report modal on click, portaled to document.body", () => {
    render(
      <MemoryRouter>
        <BugReportTrigger />
      </MemoryRouter>,
    );

    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).toBeNull();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- BugReportTrigger`
Expected: FAIL — cannot find module `./BugReportTrigger`

- [ ] **Step 3: Implement the trigger**

Create `frontend/src/components/BugReportTrigger.tsx`:

```tsx
import { useState } from "react";
import { createPortal } from "react-dom";
import { Bug } from "lucide-react";
import BugReportModal from "./BugReportModal";

export default function BugReportTrigger() {
  const [open, setOpen] = useState(false);

  return createPortal(
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label="מצאתי באג"
        className="fixed top-3 left-3 text-gray-500 hover:text-indigo-600 z-[100]"
        data-testid="bug-report-trigger"
      >
        <Bug size={22} />
      </button>
      {open && <BugReportModal onClose={() => setOpen(false)} />}
    </>,
    document.body,
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- BugReportTrigger`
Expected: 1 passed

- [ ] **Step 5: Mount it in `Layout.tsx`**

In `frontend/src/components/Layout.tsx`, add the import:

```tsx
import BugReportTrigger from "./BugReportTrigger";
```

And render it as a direct child of the root div, right after `<UnifiedNav />` (line 34) — its DOM position doesn't matter since it portals to `document.body`, but it must be inside the React tree so its own state/portal mounts when `Layout` mounts:

```tsx
    <div className="h-[100dvh] flex flex-col md:mr-24 dark:bg-gray-900 dark:text-gray-100">
      <UnifiedNav />
      <BugReportTrigger />
      {helpOpen && <HelpModal onClose={() => setHelpOpen(false)} gimelimEnabled={gimelimEnabled} initialTab={helpTab} />}
```

- [ ] **Step 6: Manually verify in the browser**

Run: `.\dev.ps1` (or ensure the dev stack is already running), open `http://localhost:5173`, log in, and confirm the bug icon appears near the top-left and opens the modal with a screenshot preview.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/BugReportTrigger.tsx frontend/src/components/BugReportTrigger.test.tsx frontend/src/components/Layout.tsx
git commit -m "feat: add portal-mounted bug report trigger to Layout"
```

---

### Task 8: Admin `BugReportsContent` + `AdminSettingsPage` wiring

**Files:**
- Create: `frontend/src/pages/admin/BugReportsContent.tsx`
- Test: `frontend/src/pages/admin/BugReportsContent.test.tsx`
- Modify: `frontend/src/pages/admin/AdminSettingsPage.tsx`
- Modify: `frontend/src/i18n/he.json`

**Interfaces:**
- Consumes: `listBugReports`, `updateBugReportStatus`, `getBugReportJson`, `fetchBugReportScreenshot`, `BugReportSummary` (Task 5)
- Produces: `BugReportsContent()` (named export, matching `SystemSettingsContent`/`AdminInviteCodesContent` conventions)

- [ ] **Step 1: Add the i18n key**

In `frontend/src/i18n/he.json`, add `admin_bug_reports` to the `nav` section, right after `"admin_changelog": "יומן שינויים",` (line 81):

```json
    "admin_changelog": "יומן שינויים",
    "admin_bug_reports": "דיווחי באגים",
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/pages/admin/BugReportsContent.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BugReportsContent } from "./BugReportsContent";
import * as bugReportsApi from "../../api/bugReports";

vi.mock("../../api/bugReports", async () => {
  const actual = await vi.importActual<typeof import("../../api/bugReports")>("../../api/bugReports");
  return {
    ...actual,
    listBugReports: vi.fn(),
    updateBugReportStatus: vi.fn(),
    getBugReportJson: vi.fn(),
    fetchBugReportScreenshot: vi.fn(),
  };
});

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const SAMPLE_REPORT = {
  id: "r1",
  reporter_id: "s1",
  description: "the calendar is blank",
  severity: "high" as const,
  status: "open" as const,
  route: "/calendar",
  nav_history: [{ path: "/", timestamp: "2026-07-25T10:00:00Z" }],
  audit_snapshot: [{ action: "login", entity_type: "soldier" }],
  user_snapshot: { full_name: "Test Soldier" },
  has_screenshot: false,
  created_at: "2026-07-25T10:05:00Z",
  updated_at: "2026-07-25T10:05:00Z",
};

describe("BugReportsContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({ items: [SAMPLE_REPORT], total: 1 });
  });

  it("renders the report list", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByText("the calendar is blank")).toBeInTheDocument());
    expect(screen.getByText("Test Soldier")).toBeInTheDocument();
  });

  it("updates status via the dropdown", async () => {
    vi.mocked(bugReportsApi.updateBugReportStatus).mockResolvedValue({ ...SAMPLE_REPORT, status: "resolved" });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-status-r1")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("bug-report-status-r1"), { target: { value: "resolved" } });

    await waitFor(() => expect(bugReportsApi.updateBugReportStatus).toHaveBeenCalledWith("r1", "resolved"));
  });

  it("filters by severity", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-filter-severity")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("bug-report-filter-severity"), { target: { value: "high" } });

    await waitFor(() => expect(bugReportsApi.listBugReports).toHaveBeenLastCalledWith(
      expect.objectContaining({ severity: "high" }),
    ));
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- BugReportsContent`
Expected: FAIL — cannot find module `./BugReportsContent`

- [ ] **Step 4: Implement the admin content component**

Create `frontend/src/pages/admin/BugReportsContent.tsx`:

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  listBugReports,
  updateBugReportStatus,
  getBugReportJson,
  fetchBugReportScreenshot,
  BugReportSummary,
  BugReportSeverity,
  BugReportStatus,
} from "../../api/bugReports";

const SEVERITY_LABELS: Record<BugReportSeverity, string> = { low: "נמוכה", medium: "בינונית", high: "גבוהה" };
const SEVERITY_COLORS: Record<BugReportSeverity, string> = {
  low: "bg-gray-100 text-gray-700",
  medium: "bg-yellow-100 text-yellow-800",
  high: "bg-red-100 text-red-800",
};
const STATUS_LABELS: Record<BugReportStatus, string> = { open: "פתוח", in_progress: "בטיפול", resolved: "טופל" };

export function BugReportsContent() {
  const [severityFilter, setSeverityFilter] = useState<BugReportSeverity | "">("");
  const [statusFilter, setStatusFilter] = useState<BugReportStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [jsonById, setJsonById] = useState<Record<string, string>>({});
  const [screenshotUrlById, setScreenshotUrlById] = useState<Record<string, string>>({});
  const limit = 20;

  const query = useQuery({
    queryKey: ["bug-reports", severityFilter, statusFilter, offset],
    queryFn: () =>
      listBugReports({
        severity: severityFilter || undefined,
        status: statusFilter || undefined,
        offset,
        limit,
      }),
  });

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const pages = Math.ceil(total / limit);

  async function handleStatusChange(id: string, status: BugReportStatus) {
    await updateBugReportStatus(id, status);
    await query.refetch();
  }

  async function loadScreenshot(id: string) {
    if (screenshotUrlById[id]) return;
    const blob = await fetchBugReportScreenshot(id);
    setScreenshotUrlById((prev) => ({ ...prev, [id]: URL.createObjectURL(blob) }));
  }

  function toggleExpand(report: BugReportSummary) {
    if (expandedId === report.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(report.id);
    if (report.has_screenshot) void loadScreenshot(report.id);
  }

  async function loadJson(id: string) {
    if (jsonById[id]) return;
    const data = await getBugReportJson(id);
    setJsonById((prev) => ({ ...prev, [id]: JSON.stringify(data, null, 2) }));
  }

  return (
    <div dir="rtl">
      <div className="flex gap-2 mb-4">
        <select
          value={severityFilter}
          onChange={(e) => { setSeverityFilter(e.target.value as BugReportSeverity | ""); setOffset(0); }}
          className="border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600"
          data-testid="bug-report-filter-severity"
        >
          <option value="">כל החומרות</option>
          <option value="low">נמוכה</option>
          <option value="medium">בינונית</option>
          <option value="high">גבוהה</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value as BugReportStatus | ""); setOffset(0); }}
          className="border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600"
          data-testid="bug-report-filter-status"
        >
          <option value="">כל הסטטוסים</option>
          <option value="open">פתוח</option>
          <option value="in_progress">בטיפול</option>
          <option value="resolved">טופל</option>
        </select>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-right border-b dark:border-gray-700">
            <th className="p-2">תאריך</th>
            <th className="p-2">מדווח</th>
            <th className="p-2">חומרה</th>
            <th className="p-2">סטטוס</th>
            <th className="p-2">תיאור</th>
          </tr>
        </thead>
        <tbody>
          {items.map((report) => (
            <>
              <tr
                key={report.id}
                className="border-b dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700"
                onClick={() => toggleExpand(report)}
                data-testid={`bug-report-row-${report.id}`}
              >
                <td className="p-2">{new Date(report.created_at).toLocaleString("he-IL")}</td>
                <td className="p-2">{(report.user_snapshot?.full_name as string) ?? "—"}</td>
                <td className="p-2">
                  <span className={`px-2 py-0.5 rounded text-xs ${SEVERITY_COLORS[report.severity]}`}>
                    {SEVERITY_LABELS[report.severity]}
                  </span>
                </td>
                <td className="p-2" onClick={(e) => e.stopPropagation()}>
                  <select
                    value={report.status}
                    onChange={(e) => handleStatusChange(report.id, e.target.value as BugReportStatus)}
                    className="border rounded px-1 py-0.5 text-xs dark:bg-gray-700 dark:border-gray-600"
                    data-testid={`bug-report-status-${report.id}`}
                  >
                    <option value="open">{STATUS_LABELS.open}</option>
                    <option value="in_progress">{STATUS_LABELS.in_progress}</option>
                    <option value="resolved">{STATUS_LABELS.resolved}</option>
                  </select>
                </td>
                <td className="p-2 truncate max-w-xs">{report.description}</td>
              </tr>
              {expandedId === report.id && (
                <tr key={`${report.id}-detail`} className="border-b dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
                  <td colSpan={5} className="p-4">
                    <p className="mb-2"><strong>תיאור מלא:</strong> {report.description}</p>
                    {report.has_screenshot && screenshotUrlById[report.id] && (
                      <img
                        src={screenshotUrlById[report.id]}
                        alt=""
                        className="max-w-md rounded border dark:border-gray-600 mb-2"
                      />
                    )}
                    <p className="mb-1"><strong>מסלול ניווט:</strong></p>
                    <ul className="list-disc pr-5 mb-2 text-xs">
                      {(report.nav_history ?? []).map((h, i) => <li key={i}>{h.path} — {h.timestamp}</li>)}
                    </ul>
                    <p className="mb-1"><strong>פעולות אחרונות ביומן:</strong></p>
                    <ul className="list-disc pr-5 mb-2 text-xs">
                      {(report.audit_snapshot ?? []).map((a, i) => (
                        <li key={i}>{String(a.action)} — {String(a.entity_type)}</li>
                      ))}
                    </ul>
                    <button
                      onClick={() => loadJson(report.id)}
                      className="text-xs text-indigo-600 hover:text-indigo-800"
                      data-testid={`bug-report-view-json-${report.id}`}
                    >
                      הצג JSON
                    </button>
                    {jsonById[report.id] && (
                      <pre className="text-xs bg-gray-100 dark:bg-gray-800 p-2 rounded mt-2 overflow-x-auto">
                        {jsonById[report.id]}
                      </pre>
                    )}
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>

      {pages > 1 && (
        <div className="flex justify-center gap-2 mt-4">
          {Array.from({ length: pages }, (_, i) => (
            <button
              key={i}
              onClick={() => setOffset(i * limit)}
              className={`px-3 py-1 rounded text-sm ${offset === i * limit ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-700 dark:text-gray-300"}`}
            >
              {i + 1}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- BugReportsContent`
Expected: 3 passed

- [ ] **Step 6: Wire the 4th tab into `AdminSettingsPage.tsx`**

Replace the full contents of `frontend/src/pages/admin/AdminSettingsPage.tsx`:

```tsx
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import TabBar from "../../components/TabBar";
import { SystemSettingsContent, ChangelogContent } from "../SystemSettingsPage";
import { AdminInviteCodesContent } from "../AdminInviteCodesPage";
import { BugReportsContent } from "./BugReportsContent";

export default function AdminSettingsPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("tab") ?? "0");
  const activeTab = raw >= 0 && raw <= 3 ? raw : 0;
  const setTab = (i: number) => setSearchParams({ tab: String(i) }, { replace: true });

  const tabs = [
    t("nav.admin_settings"),
    t("nav.admin_invite_codes"),
    t("nav.admin_changelog"),
    t("nav.admin_bug_reports"),
  ];

  return (
    <Layout>
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} />
      {activeTab === 0 && <SystemSettingsContent />}
      {activeTab === 1 && <AdminInviteCodesContent />}
      {activeTab === 2 && <ChangelogContent />}
      {activeTab === 3 && <BugReportsContent />}
    </Layout>
  );
}
```

- [ ] **Step 7: Run the full frontend test suite**

Run: `npm test`
Expected: all passed

- [ ] **Step 8: Run typecheck and lint**

Run: `npm run typecheck && npm run lint`
Expected: no errors, zero warnings

- [ ] **Step 9: Manually verify in the browser**

Log in as an admin, go to System Settings, confirm the new "דיווחי באגים" tab appears 4th, lists submitted reports, and that changing status/expanding a row/viewing JSON all work.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/admin/BugReportsContent.tsx frontend/src/pages/admin/BugReportsContent.test.tsx frontend/src/pages/admin/AdminSettingsPage.tsx frontend/src/i18n/he.json
git commit -m "feat: add admin bug reports tab"
```

---

## Post-implementation checklist

- [ ] `pytest -q` (backend fast suite) passes
- [ ] `npm test` (frontend) passes
- [ ] `npm run lint` and `npm run typecheck` pass
- [ ] Manually submit a bug report as a regular soldier, then verify it in the admin tab as an admin, including screenshot, JSON view, and status update
