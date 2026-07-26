# Announcements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let commanders/duty-managers announce to soldiers in their scope and admins broadcast org-wide, with recipients seeing it as a notification (distinct icon for scoped vs. org-wide), and senders getting a history view with read receipts.

**Architecture:** Reuse and extend the existing (currently unwired) `broadcast_announcement`/`POST /notifications/announce` backend machinery. Add a `read_at` timestamp to `Notification` and a new `Announcement` table (one row per broadcast, so senders can list what they've sent and see per-recipient read status). Add a new `NotificationType.system_announcement` value so org-wide vs. scoped announcements render with different icons. Build the missing frontend: a compose page with a scope-aware target picker, a sent-history list, and a read-receipt view.

**Tech Stack:** FastAPI + SQLAlchemy (`MappedAsDataclass`) + Alembic + pytest (backend); React + TypeScript + react-query + vitest (frontend). No new libraries.

## Global Constraints

- Backend: `pytest -q` must stay green after every task; run `pytest -m notifications -q` for fast targeted checks while iterating (see `backend/pyproject.toml:71`).
- Frontend: `npm test` (vitest) must stay green; `npm run lint` zero warnings.
- Hebrew UI strings only go in `frontend/src/i18n/he.json` — never hardcode Hebrew text directly in `.tsx` files (existing convention; `HakpazaPage.tsx`'s hardcoded Hebrew nav labels are a pre-existing exception in `commanderItems`, not something to imitate).
- Icon choice is driven by scope (org-wide vs. targeted), never by sender role.
- Never commit directly to `master` or `dev` — this work happens on whatever feature branch the executing skill sets up.

---

### Task 1: Data model — `read_at`, `system_announcement` type, `Announcement` table

**Files:**
- Modify: `backend/app/db/models.py` (Notification class, NotificationType enum, new Announcement class)
- Create: `backend/alembic/versions/<rev1>_add_read_at_and_system_announcement.py`
- Create: `backend/alembic/versions/<rev2>_create_announcements_table.py`
- Test: `backend/tests/integration/test_notifications_api.py` (one new smoke test)

**Interfaces:**
- Produces: `NotificationType.system_announcement` (str enum value `"system_announcement"`), `Notification.read_at: datetime | None`, new `Announcement` model with fields `id, sender_id, title, body, type, hierarchy_node_ids, recipient_count, created_at`.
- Consumes: nothing (foundation task).

- [ ] **Step 1: Generate the first migration**

Run (from `backend/`, with `.venv` active):
```bash
alembic revision -m "add read_at and system_announcement type"
```
This prints the new revision id — call it `<rev1>` below (alembic derives it from the current head, which is `d22c211a3039`).

- [ ] **Step 2: Write the migration body**

Open the generated file and replace its contents with:

```python
"""add read_at and system_announcement type

Revision ID: <rev1>
Revises: d22c211a3039
Create Date: 2026-07-26

"""
from alembic import op
import sqlalchemy as sa

revision = "<rev1>"
down_revision = "d22c211a3039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'system_announcement'")
    op.add_column("notifications", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "read_at")
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op for the type.
```

(Confirm `down_revision` is exactly `"d22c211a3039"` — that's the current single head, verify with `alembic heads` if unsure.)

- [ ] **Step 3: Generate the second migration**

```bash
alembic revision -m "create announcements table"
```
Call the printed id `<rev2>`.

- [ ] **Step 4: Write the second migration body**

```python
"""create announcements table

Revision ID: <rev2>
Revises: <rev1>
Create Date: 2026-07-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "<rev2>"
down_revision = "<rev1>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("type", postgresql.ENUM("announcement", "system_announcement", name="notification_type", create_type=False), nullable=False),
        sa.Column("hierarchy_node_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        sa.Column("recipient_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_announcements_sender_id", "announcements", ["sender_id"])


def downgrade() -> None:
    op.drop_index("ix_announcements_sender_id", table_name="announcements")
    op.drop_table("announcements")
```

- [ ] **Step 5: Update `NotificationType` enum in the model**

In `backend/app/db/models.py`, find the `NotificationType` enum class (it ends with `transfer_request_rejected = "transfer_request_rejected"`, currently around line 942). Add a new member right after it:

```python
    transfer_request_pending = "transfer_request_pending"
    transfer_request_rejected = "transfer_request_rejected"
    system_announcement = "system_announcement"
```

- [ ] **Step 6: Add `read_at` to `Notification`**

In the same file, find the `Notification` class:

```python
class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notification_type"), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    reference_type: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    is_read: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
```

Add `read_at` right after `is_read`:

```python
    is_read: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
```

- [ ] **Step 7: Add the `Announcement` model**

Add this new class right after the `Notification` class in `backend/app/db/models.py`:

```python
class Announcement(Base):
    __tablename__ = "announcements"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    sender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notification_type"), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    hierarchy_node_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
```

`Integer` is already imported at the top of `models.py` (`from sqlalchemy import ... Integer ...`) — no new imports needed.

- [ ] **Step 8: Write a smoke test that proves the schema is correct**

Append to `backend/tests/integration/test_notifications_api.py` (add `Announcement` to the existing `from app.db.models import Notification, NotificationType` import line, making it `from app.db.models import Announcement, Notification, NotificationType`):

```python
def test_read_at_set_on_mark_read(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001018")
    headers = auth_headers(s)
    n = Notification(soldier_id=s.id, type=NotificationType.announcement, title="Read me too")
    admin_session.add(n)
    admin_session.commit()
    nid = n.id
    resp = client.patch(f"/api/notifications/{nid}/read", headers=headers)
    assert resp.status_code == 200
    admin_session.refresh(n)
    assert n.read_at is not None


def test_announcement_row_can_be_created_directly(admin_session: Session):
    sender = create_soldier(admin_session, personal_number="9001019", role="admin")
    a = Announcement(sender_id=sender.id, title="Org update", recipient_count=3, type=NotificationType.system_announcement)
    admin_session.add(a)
    admin_session.commit()
    admin_session.refresh(a)
    assert a.id is not None
    assert a.hierarchy_node_ids is None
    assert a.created_at is not None
```

- [ ] **Step 9: Run the tests to verify they fail (migration not yet applied would error; if the model changes are wrong, these will show it)**

```bash
pytest tests/integration/test_notifications_api.py -k "read_at_set_on_mark_read or announcement_row_can_be_created" -v
```
Expected at this point: PASS (migrations run automatically against the test DB via `tests/conftest.py`'s `alembic upgrade head` — if Steps 1-7 are correct these should already pass). If they fail, re-check the migration `down_revision` chain and the model field additions before proceeding.

- [ ] **Step 10: Run the full notifications test area to confirm nothing else broke**

```bash
pytest -m notifications -q
```
Expected: all pass (this exercises the existing `test_admin_can_broadcast_org_wide` etc., proving the schema change didn't break the current announce flow).

- [ ] **Step 11: Commit**

```bash
git add backend/alembic/versions backend/app/db/models.py backend/tests/integration/test_notifications_api.py
git commit -m "feat: add read_at, system_announcement type, and announcements table"
```

---

### Task 2: Service layer — broadcast type selection, read receipts, scope, history

**Files:**
- Modify: `backend/app/services/notifications.py`
- Test: `backend/tests/integration/test_notifications_api.py`

**Interfaces:**
- Consumes: `Announcement`, `NotificationType.system_announcement`, `Notification.read_at` from Task 1.
- Produces (used by Task 3's routes):
  - `broadcast_announcement(session, *, title, body=None, hierarchy_node_ids=None, actor_id=None) -> Announcement` (return type changed from `int` to `Announcement`)
  - `scope_nodes_for_announcement(session, user: Soldier) -> list[HierarchyNode]`
  - `list_sent_announcements(session, *, sender_id, offset=0, limit=20) -> tuple[list[tuple[Announcement, int]], int]` (each tuple is `(announcement, read_count)`)
  - `get_announcement_recipients(session, *, announcement_id, sender_id) -> list[tuple[Soldier, bool, datetime | None]] | None` (each tuple is `(soldier, is_read, read_at)`; `None` means not found or caller doesn't own it)

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/integration/test_notifications_api.py` (extend the existing `from app.db.models import ...` line to include `HierarchyNode`; it's likely not yet imported there — check the top of the file and add it if missing):

```python
def test_broadcast_org_wide_uses_system_announcement_type(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001020", role="admin")
    headers = auth_headers(admin)
    recipient = create_soldier(admin_session, personal_number="9001021")
    resp = client.post("/api/notifications/announce", headers=headers, json={"title": "org wide"})
    assert resp.status_code == 201
    notif = admin_session.execute(
        select(Notification).where(Notification.soldier_id == recipient.id, Notification.title == "org wide")
    ).scalar_one()
    assert notif.type == NotificationType.system_announcement
    assert notif.reference_type == "announcement"
    assert notif.reference_id == uuid.UUID(resp.json()["id"])


def test_broadcast_scoped_uses_announcement_type(client: TestClient, admin_session: Session):
    unit_a = create_node(admin_session, level="unit", name="UnitScopeType")
    dm = create_soldier(admin_session, personal_number="9001022", role="duty_manager", hierarchy_node_id=unit_a.id)
    recipient = create_soldier(admin_session, personal_number="9001023", hierarchy_node_id=unit_a.id)
    headers = auth_headers(dm)
    resp = client.post(
        "/api/notifications/announce", headers=headers,
        json={"title": "scoped", "hierarchy_node_ids": [str(unit_a.id)]},
    )
    assert resp.status_code == 201
    notif = admin_session.execute(
        select(Notification).where(Notification.soldier_id == recipient.id, Notification.title == "scoped")
    ).scalar_one()
    assert notif.type == NotificationType.announcement


def test_admin_scoped_announcement_still_uses_scoped_type(client: TestClient, admin_session: Session):
    unit_a = create_node(admin_session, level="unit", name="UnitAdminScoped")
    admin = create_soldier(admin_session, personal_number="9001024", role="admin")
    recipient = create_soldier(admin_session, personal_number="9001025", hierarchy_node_id=unit_a.id)
    headers = auth_headers(admin)
    resp = client.post(
        "/api/notifications/announce", headers=headers,
        json={"title": "admin scoped", "hierarchy_node_ids": [str(unit_a.id)]},
    )
    assert resp.status_code == 201
    notif = admin_session.execute(
        select(Notification).where(Notification.soldier_id == recipient.id, Notification.title == "admin scoped")
    ).scalar_one()
    assert notif.type == NotificationType.announcement  # scope-driven, not sender-driven
```

`select` needs to be imported at the top of the test file: add `from sqlalchemy import select` if not already present (check the existing import block first).

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/integration/test_notifications_api.py -k "system_announcement_type or scoped_uses_announcement_type or admin_scoped_announcement" -v
```
Expected: FAIL — `broadcast_announcement` still always uses `NotificationType.announcement`, and the route doesn't return an `"id"` field yet (this second part will be fixed in Task 3, so for now these tests will fail on the `resp.json()["id"]` line or the type assertion — that's expected; Task 3 makes them fully pass. For this task, focus on getting the `type` assertions right by running a trimmed version without the `reference_id` line if needed, or proceed knowing full green comes after Task 3).

- [ ] **Step 3: Update `broadcast_announcement`**

In `backend/app/services/notifications.py`, find:

```python
def broadcast_announcement(session: Session, *, title: str, body: str | None = None,
                           hierarchy_node_ids: list[uuid.UUID] | None = None,
                           actor_id: uuid.UUID | None = None) -> int:
    if hierarchy_node_ids:
        nodes = session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(hierarchy_node_ids))
        ).scalars().all()
        path_sets = [set(n.path_ids) for n in nodes if n.path_ids]
        if path_sets:
            combined_paths = set().union(*path_sets)
            soldiers = session.execute(
                select(Soldier).where(
                    Soldier.hierarchy_node_id.in_(
                        select(HierarchyNode.id).where(
                            HierarchyNode.path_ids.overlap(list(combined_paths))
                        )
                    )
                )
            ).scalars().all()
        else:
            soldiers = []
    else:
        soldiers = session.execute(select(Soldier)).scalars().all()
    count = 0
    for s in soldiers:
        create_notification(session, soldier_id=s.id, type=NotificationType.announcement,
                            title=title, body=body, actor_id=actor_id)
        count += 1
    return count
```

Replace it entirely with:

```python
def broadcast_announcement(session: Session, *, title: str, body: str | None = None,
                           hierarchy_node_ids: list[uuid.UUID] | None = None,
                           actor_id: uuid.UUID | None = None) -> Announcement:
    if hierarchy_node_ids:
        nodes = session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(hierarchy_node_ids))
        ).scalars().all()
        path_sets = [set(n.path_ids) for n in nodes if n.path_ids]
        if path_sets:
            combined_paths = set().union(*path_sets)
            soldiers = session.execute(
                select(Soldier).where(
                    Soldier.hierarchy_node_id.in_(
                        select(HierarchyNode.id).where(
                            HierarchyNode.path_ids.overlap(list(combined_paths))
                        )
                    )
                )
            ).scalars().all()
        else:
            soldiers = []
    else:
        soldiers = session.execute(select(Soldier)).scalars().all()

    notif_type = NotificationType.announcement if hierarchy_node_ids else NotificationType.system_announcement
    announcement = Announcement(
        sender_id=actor_id, title=title, recipient_count=len(soldiers), type=notif_type,
        body=body, hierarchy_node_ids=hierarchy_node_ids,
    )
    session.add(announcement)
    session.flush()
    for s in soldiers:
        create_notification(session, soldier_id=s.id, type=notif_type,
                            title=title, body=body, actor_id=actor_id,
                            reference_type="announcement", reference_id=announcement.id)
    return announcement
```

- [ ] **Step 4: Add `Announcement` to this file's imports**

At the top of `backend/app/services/notifications.py`, find:

```python
from app.db.models import (
    CommanderNotificationDepth,
    CommanderNotificationScope,
    DutyManagerScope,
    EmailOutbox,
    HierarchyNode,
    Notification,
    NotificationPreference,
    NotificationType,
    Soldier,
    TelegramLink,
    TelegramOutbox,
)
```

Change to:

```python
from app.db.models import (
    Announcement,
    CommanderNotificationDepth,
    CommanderNotificationScope,
    DutyManagerScope,
    EmailOutbox,
    HierarchyNode,
    Notification,
    NotificationPreference,
    NotificationType,
    Soldier,
    TelegramLink,
    TelegramOutbox,
)
from app.auth.authz import scope_root_ids
```

- [ ] **Step 5: Set `read_at` in `mark_read`/`mark_all_read`**

Find:

```python
def mark_read(session: Session, *, notification_id: uuid.UUID, soldier_id: uuid.UUID) -> Notification | None:
    n = session.execute(select(Notification).where(Notification.id == notification_id, Notification.soldier_id == soldier_id)).scalar_one_or_none()
    if n:
        n.is_read = True
    return n


def mark_all_read(session: Session, *, soldier_id: uuid.UUID) -> int:
    notifs = list(session.execute(select(Notification).where(Notification.soldier_id == soldier_id, Notification.is_read == False)).scalars().all())  # noqa: E712
    for n in notifs:
        n.is_read = True
    return len(notifs)
```

Replace with:

```python
def mark_read(session: Session, *, notification_id: uuid.UUID, soldier_id: uuid.UUID) -> Notification | None:
    n = session.execute(select(Notification).where(Notification.id == notification_id, Notification.soldier_id == soldier_id)).scalar_one_or_none()
    if n:
        n.is_read = True
        n.read_at = datetime.now(timezone.utc)
    return n


def mark_all_read(session: Session, *, soldier_id: uuid.UUID) -> int:
    notifs = list(session.execute(select(Notification).where(Notification.soldier_id == soldier_id, Notification.is_read == False)).scalars().all())  # noqa: E712
    now = datetime.now(timezone.utc)
    for n in notifs:
        n.is_read = True
        n.read_at = now
    return len(notifs)
```

(`datetime` and `timezone` are already imported at the top of the file: `from datetime import datetime, timedelta, timezone`.)

- [ ] **Step 6: Add `scope_nodes_for_announcement`, `list_sent_announcements`, `get_announcement_recipients`**

Add these new functions right after `broadcast_announcement`:

```python
def scope_nodes_for_announcement(session: Session, user: Soldier) -> list[HierarchyNode]:
    if user.role == "admin":
        return []
    roots = scope_root_ids(session, user)
    if not roots:
        return []
    return list(session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(roots))).scalars().all())


def list_sent_announcements(session: Session, *, sender_id: uuid.UUID,
                            offset: int = 0, limit: int = 20) -> tuple[list[tuple[Announcement, int]], int]:
    total = len(session.execute(
        select(Announcement.id).where(Announcement.sender_id == sender_id)
    ).scalars().all())
    rows = list(session.execute(
        select(Announcement).where(Announcement.sender_id == sender_id)
        .order_by(Announcement.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all())
    result = []
    for a in rows:
        read_count = len(session.execute(
            select(Notification.id).where(
                Notification.reference_type == "announcement",
                Notification.reference_id == a.id,
                Notification.is_read == True,  # noqa: E712
            )
        ).scalars().all())
        result.append((a, read_count))
    return result, total


def get_announcement_recipients(session: Session, *, announcement_id: uuid.UUID,
                                sender_id: uuid.UUID) -> list[tuple[Soldier, bool, datetime | None]] | None:
    announcement = session.get(Announcement, announcement_id)
    if announcement is None or announcement.sender_id != sender_id:
        return None
    rows = session.execute(
        select(Notification, Soldier)
        .join(Soldier, Soldier.id == Notification.soldier_id)
        .where(Notification.reference_type == "announcement", Notification.reference_id == announcement_id)
    ).all()
    return [(soldier, notif.is_read, notif.read_at) for notif, soldier in rows]
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
pytest tests/integration/test_notifications_api.py -k "system_announcement_type or scoped_uses_announcement_type or admin_scoped_announcement or read_at_set" -v
```
Expected: the `type` assertions pass now. The `resp.json()["id"]` assertion in `test_broadcast_org_wide_uses_system_announcement_type` will still fail (route doesn't return `id` yet) — that's expected and fixed in Task 3. If you want a fully-green run for this task alone, temporarily comment out the `assert notif.reference_id == ...` line, run, then restore it before committing (Task 3 will make it pass for real).

Actually — to keep this task's tests genuinely green without a temporary hack, reorder: **do Task 3 immediately after this step before committing Task 2's tests**, OR commit Task 2 now with the tests present but skip running the `reference_id` assertion until Task 3 lands. The cleanest approach: commit the service-layer change now (Step 8 below); the two new tests will be finalized (fully green) as part of Task 3's own test run.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/notifications.py backend/tests/integration/test_notifications_api.py
git commit -m "feat: broadcast_announcement picks type by scope, adds read_at tracking and history queries"
```

---

### Task 3: Routes — extend announce response, add scope/history/recipients endpoints

**Files:**
- Modify: `backend/app/routes/notifications.py`
- Test: `backend/tests/integration/test_notifications_api.py`

**Interfaces:**
- Consumes: `svc.broadcast_announcement` (now returns `Announcement`), `svc.scope_nodes_for_announcement`, `svc.list_sent_announcements`, `svc.get_announcement_recipients` from Task 2.
- Produces (used by Task 4/5's frontend):
  - `POST /notifications/announce` → `{"id": str, "sent": int}` (status 201)
  - `GET /notifications/announce/scope` → `[{"id": str, "name": str, "level": str}, ...]`
  - `GET /notifications/announcements?offset=&limit=` → `{"items": [...], "total": int}`, each item `{id, title, body, type, hierarchy_node_ids, recipient_count, read_count, created_at}`
  - `GET /notifications/announcements/{id}/recipients` → `[{"soldier_id": str, "full_name": str, "is_read": bool, "read_at": str | null}, ...]` (404 if not found or not owned by caller)

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/integration/test_notifications_api.py`:

```python
def test_announce_scope_returns_own_roots_for_dm(client: TestClient, admin_session: Session):
    unit_a = create_node(admin_session, level="unit", name="ScopeEndpointUnit")
    dm = create_soldier(admin_session, personal_number="9001026", role="duty_manager", hierarchy_node_id=unit_a.id)
    headers = auth_headers(dm)
    resp = client.get("/api/notifications/announce/scope", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == str(unit_a.id)
    assert data[0]["name"] == "ScopeEndpointUnit"


def test_announce_scope_empty_for_admin(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001027", role="admin")
    headers = auth_headers(admin)
    resp = client.get("/api/notifications/announce/scope", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_announce_returns_id_and_sent_count(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001028", role="admin")
    create_soldier(admin_session, personal_number="9001029")
    headers = auth_headers(admin)
    resp = client.post("/api/notifications/announce", headers=headers, json={"title": "count me"})
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["sent"] >= 2  # admin + the extra soldier created above (and any others in this test DB)


def test_list_sent_announcements_history(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001030", role="admin")
    headers = auth_headers(admin)
    send_resp = client.post("/api/notifications/announce", headers=headers, json={"title": "history item"})
    announcement_id = send_resp.json()["id"]
    resp = client.get("/api/notifications/announcements", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    match = next(i for i in items if i["id"] == announcement_id)
    assert match["title"] == "history item"
    assert match["read_count"] == 0
    assert match["recipient_count"] >= 1


def test_announcement_recipients_endpoint(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001031", role="admin")
    recipient = create_soldier(admin_session, personal_number="9001032")
    headers = auth_headers(admin)
    send_resp = client.post("/api/notifications/announce", headers=headers, json={"title": "recipients test"})
    announcement_id = send_resp.json()["id"]
    resp = client.get(f"/api/notifications/announcements/{announcement_id}/recipients", headers=headers)
    assert resp.status_code == 200
    rows = resp.json()
    match = next(r for r in rows if r["soldier_id"] == str(recipient.id))
    assert match["full_name"] == recipient.full_name
    assert match["is_read"] is False
    assert match["read_at"] is None


def test_announcement_recipients_404_for_non_owner(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001033", role="admin")
    other_admin = create_soldier(admin_session, personal_number="9001034", role="admin")
    headers = auth_headers(admin)
    send_resp = client.post("/api/notifications/announce", headers=headers, json={"title": "not yours"})
    announcement_id = send_resp.json()["id"]
    other_headers = auth_headers(other_admin)
    resp = client.get(f"/api/notifications/announcements/{announcement_id}/recipients", headers=other_headers)
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/integration/test_notifications_api.py -k "announce_scope or announce_returns_id or list_sent_announcements or announcement_recipients" -v
```
Expected: FAIL — none of these routes exist yet (404 on the new GET paths; `AnnounceBody` response has no `"id"` key yet).

- [ ] **Step 3: Add new imports and response models**

In `backend/app/routes/notifications.py`, change the models import line:

```python
from app.db.models import CommanderNotificationScope, HierarchyNode, Notification, NotificationPreference, NotificationType, Soldier, SwapRequest
```
to:
```python
from app.db.models import Announcement, CommanderNotificationScope, HierarchyNode, Notification, NotificationPreference, NotificationType, Soldier, SwapRequest
```

Add these new Pydantic models right after `class AnnounceBody(BaseModel): ...`:

```python
class AnnounceOut(BaseModel):
    id: uuid.UUID
    sent: int


class ScopeNodeOut(BaseModel):
    id: uuid.UUID
    name: str
    level: str


class AnnouncementOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str | None
    type: str
    hierarchy_node_ids: list[uuid.UUID] | None
    recipient_count: int
    read_count: int
    created_at: datetime


class PaginatedAnnouncements(BaseModel):
    items: list[AnnouncementOut]
    total: int


class AnnouncementRecipientOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    is_read: bool
    read_at: datetime | None
```

- [ ] **Step 4: Update the `announce` route to return id + sent, and add the three new routes**

Find:

```python
@router.post("/notifications/announce", status_code=201)
def announce(
    body: AnnounceBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    if user.role != "admin":
        if not body.hierarchy_node_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="org_wide_announcement_requires_admin"
            )
        if not (is_commander(session, user.id) or is_duty_manager(session, user.id)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        roots = scope_root_ids(session, user)
        for node_id in body.hierarchy_node_ids:
            node = session.get(HierarchyNode, node_id)
            if not _node_in_scope(node, roots):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="hierarchy_node_out_of_scope"
                )

    count = svc.broadcast_announcement(session, title=body.title, body=body.body,
                                        hierarchy_node_ids=body.hierarchy_node_ids,
                                        actor_id=user.id)
    session.commit()
    return {"sent": count}
```

Replace the whole thing with:

```python
@router.post("/notifications/announce", status_code=201, response_model=AnnounceOut)
def announce(
    body: AnnounceBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AnnounceOut:
    if user.role != "admin":
        if not body.hierarchy_node_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="org_wide_announcement_requires_admin"
            )
        if not (is_commander(session, user.id) or is_duty_manager(session, user.id)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        roots = scope_root_ids(session, user)
        for node_id in body.hierarchy_node_ids:
            node = session.get(HierarchyNode, node_id)
            if not _node_in_scope(node, roots):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="hierarchy_node_out_of_scope"
                )

    announcement = svc.broadcast_announcement(session, title=body.title, body=body.body,
                                              hierarchy_node_ids=body.hierarchy_node_ids,
                                              actor_id=user.id)
    session.commit()
    return AnnounceOut(id=announcement.id, sent=announcement.recipient_count)


@router.get("/notifications/announce/scope", response_model=list[ScopeNodeOut])
def announce_scope(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ScopeNodeOut]:
    nodes = svc.scope_nodes_for_announcement(session, user)
    return [ScopeNodeOut(id=n.id, name=n.name, level=n.level) for n in nodes]


@router.get("/notifications/announcements", response_model=PaginatedAnnouncements)
def list_my_announcements(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
    offset: int = 0,
    limit: int = 20,
) -> PaginatedAnnouncements:
    rows, total = svc.list_sent_announcements(session, sender_id=user.id, offset=offset, limit=limit)
    items = [
        AnnouncementOut(
            id=a.id, title=a.title, body=a.body, type=a.type.value,
            hierarchy_node_ids=a.hierarchy_node_ids, recipient_count=a.recipient_count,
            read_count=read_count, created_at=a.created_at,
        )
        for a, read_count in rows
    ]
    return PaginatedAnnouncements(items=items, total=total)


@router.get("/notifications/announcements/{announcement_id}/recipients", response_model=list[AnnouncementRecipientOut])
def announcement_recipients(
    announcement_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[AnnouncementRecipientOut]:
    result = svc.get_announcement_recipients(session, announcement_id=announcement_id, sender_id=user.id)
    if result is None:
        raise _err("not_found", 404)
    return [
        AnnouncementRecipientOut(soldier_id=s.id, full_name=s.full_name, is_read=is_read, read_at=read_at)
        for s, is_read, read_at in result
    ]
```

- [ ] **Step 5: Run all the new and Task-2 tests to verify they now pass**

```bash
pytest tests/integration/test_notifications_api.py -v
```
Expected: PASS for every test in the file, including the two carried over from Task 2 (`test_broadcast_org_wide_uses_system_announcement_type`, `test_broadcast_scoped_uses_announcement_type`, `test_admin_scoped_announcement_still_uses_scoped_type`) which now have a real `"id"` field to assert on.

- [ ] **Step 6: Run the full backend suite**

```bash
pytest -q
```
Expected: all pass (only the 3 known pre-existing `SKIPPED` CP-SAT solver tests, no failures).

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/notifications.py backend/tests/integration/test_notifications_api.py
git commit -m "feat: add announce scope, history, and recipients endpoints"
```

---

### Task 4: Frontend API wrapper, icons, and translations

**Files:**
- Create: `frontend/src/api/announcements.ts`
- Modify: `frontend/src/components/NotificationBell.tsx`
- Modify: `frontend/src/pages/NotificationsPage.tsx`
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/queryKeys.ts`
- Test: `frontend/src/components/NotificationBell.test.tsx` (new)

**Interfaces:**
- Consumes: the four endpoints from Task 3 (`POST /notifications/announce`, `GET /notifications/announce/scope`, `GET /notifications/announcements`, `GET /notifications/announcements/{id}/recipients`).
- Produces (used by Task 5): `getAnnounceScope`, `postAnnouncement`, `listAnnouncements`, `getAnnouncementRecipients` from `frontend/src/api/announcements.ts`, plus the `ScopeNode`, `AnnounceResult`, `AnnouncementDTO`, `PaginatedAnnouncements`, `AnnouncementRecipient` types.

- [ ] **Step 1: Create the API wrapper**

Create `frontend/src/api/announcements.ts`:

```typescript
import { api as client } from "./client";

export interface ScopeNode {
  id: string;
  name: string;
  level: string;
}

export interface AnnounceResult {
  id: string;
  sent: number;
}

export interface AnnouncementDTO {
  id: string;
  title: string;
  body: string | null;
  type: string;
  hierarchy_node_ids: string[] | null;
  recipient_count: number;
  read_count: number;
  created_at: string;
}

export interface PaginatedAnnouncements {
  items: AnnouncementDTO[];
  total: number;
}

export interface AnnouncementRecipient {
  soldier_id: string;
  full_name: string;
  is_read: boolean;
  read_at: string | null;
}

export function getAnnounceScope(): Promise<ScopeNode[]> {
  return client.get("/notifications/announce/scope").then((r) => r.data);
}

export function postAnnouncement(payload: {
  title: string;
  body?: string;
  hierarchy_node_ids?: string[];
}): Promise<AnnounceResult> {
  return client.post("/notifications/announce", payload).then((r) => r.data);
}

export function listAnnouncements(params?: { offset?: number; limit?: number }): Promise<PaginatedAnnouncements> {
  return client.get("/notifications/announcements", { params }).then((r) => r.data);
}

export function getAnnouncementRecipients(id: string): Promise<AnnouncementRecipient[]> {
  return client.get(`/notifications/announcements/${id}/recipients`).then((r) => r.data);
}
```

- [ ] **Step 2: Add query keys**

In `frontend/src/queryKeys.ts`, add these three lines right after the existing `notifications: (filter: string, offset: number) => ...` line:

```typescript
  announceScope: () => ["notifications", "announceScope"] as const,
  announcementsList: (offset: number) => ["notifications", "announcements", offset] as const,
  announcementRecipients: (id: string) => ["notifications", "announcements", id, "recipients"] as const,
```

- [ ] **Step 3: Write the failing icon test**

Create `frontend/src/components/NotificationBell.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import NotificationBell from "./NotificationBell";
import * as notificationsApi from "../api/notifications";

vi.mock("../api/notifications");

const baseNotification = {
  id: "n1",
  soldier_id: "s1",
  body: null,
  reference_type: null,
  reference_id: null,
  is_read: false,
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(notificationsApi.getUnreadCount).mockResolvedValue({ count: 2 });
});

describe("NotificationBell icon differentiation", () => {
  it("shows a different icon for system_announcement than for announcement", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [
        { ...baseNotification, id: "n1", title: "Scoped", type: "announcement" },
        { ...baseNotification, id: "n2", title: "Org wide", type: "system_announcement" },
      ],
      total: 2,
    });
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    );
    const bellButton = await screen.findByTestId("notification-bell");
    bellButton.click();
    const scopedRow = await screen.findByText("Scoped");
    const orgWideRow = await screen.findByText("Org wide");
    expect(scopedRow.closest("div")?.parentElement?.textContent).toContain("📢");
    expect(orgWideRow.closest("div")?.parentElement?.textContent).toContain("📣");
  });
});
```

- [ ] **Step 4: Run the test to verify it fails**

```bash
npx vitest run src/components/NotificationBell.test.tsx
```
Expected: FAIL — `system_announcement` isn't in `typeLabels` yet, so both rows show the same fallback/existing icon.

- [ ] **Step 5: Add the icon to both typeLabels maps**

In `frontend/src/components/NotificationBell.tsx`, find:

```typescript
  const typeLabels: Record<string, string> = {
    swap_offer: "🔄", swap_accepted: "✅", swap_rejected: "❌",
    exemption_approved: "✔️", exemption_rejected: "✖️",
    constraint_approved: "✔️", constraint_rejected: "✖️",
    assignment_created: "📋", assignment_removed: "🗑️",
    score_adjusted: "⭐", announcement: "📢",
    algorithm_job_done: "🤖", algorithm_job_failed: "⚠️",
  };
```

Change the `announcement` line to:

```typescript
    score_adjusted: "⭐", announcement: "📢", system_announcement: "📣",
```

In `frontend/src/pages/NotificationsPage.tsx`, find:

```typescript
  const typeLabels: Record<string, string> = {
    swap_offer: "🔄", swap_accepted: "✅", swap_rejected: "❌",
    exemption_approved: "✔️", exemption_rejected: "✖️",
    constraint_approved: "✔️", constraint_rejected: "✖️",
    assignment_created: "📋", assignment_removed: "🗑️",
    score_adjusted: "⭐", announcement: "📢",
  };
```

Change the same line the same way:

```typescript
    score_adjusted: "⭐", announcement: "📢", system_announcement: "📣",
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
npx vitest run src/components/NotificationBell.test.tsx
```
Expected: PASS.

- [ ] **Step 7: Add translations**

In `frontend/src/i18n/he.json`, in the `"nav"` object, add a new line right after `"command_dashboard": "דשבורד מפקד",` (around line 59):

```json
    "command_dashboard": "דשבורד מפקד",
    "announcements": "הכרזות",
```

Then, find the closing `},` of the `"notifications"` object (it's right before the `"register": {` key — the notifications section ends with `"type_transfer_request_pending": "בקשת העברה ממתינה"` followed by `},`). Insert a brand-new top-level section right after that `},` and before `"register": {`:

```json
  "announcements": {
    "title": "הכרזות",
    "compose_title": "הכרזה חדשה",
    "field_title": "כותרת",
    "field_body": "תוכן (אופציונלי)",
    "target_label": "נמענים",
    "target_everyone": "כלל הארגון",
    "target_my_scope": "כל מי שתחת פיקודי",
    "target_narrow": "בחר יחידה ספציפית",
    "add_unit": "הוסף יחידה",
    "remove_unit": "הסר",
    "submit": "שלח הכרזה",
    "submitting": "שולח...",
    "sent_success": "ההכרזה נשלחה בהצלחה",
    "history_title": "היסטוריית הכרזות",
    "no_history": "עדיין לא נשלחו הכרזות",
    "recipients": "נמענים",
    "read_count": "{{read}} מתוך {{total}} קראו",
    "view_recipients": "הצג נמענים",
    "hide_recipients": "הסתר נמענים",
    "recipient_read": "נקרא",
    "recipient_unread": "לא נקרא"
  },
```

- [ ] **Step 8: Run the frontend suite to confirm nothing broke**

```bash
npx vitest run
```
Expected: all tests pass, including the new `NotificationBell.test.tsx`.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/announcements.ts frontend/src/components/NotificationBell.tsx frontend/src/pages/NotificationsPage.tsx frontend/src/i18n/he.json frontend/src/queryKeys.ts frontend/src/components/NotificationBell.test.tsx
git commit -m "feat: add announcements API client, distinct system-wide icon, and translations"
```

---

### Task 5: Frontend — Announcements page (compose + history + read receipts) and nav entry

**Files:**
- Create: `frontend/src/pages/AnnouncementsPage.tsx`
- Create: `frontend/src/pages/AnnouncementsPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/UnifiedNav.tsx`
- Modify: `frontend/src/components/HierarchyNodePickerModal.tsx` (small signature enhancement, see Step 0)

**Interfaces:**
- Consumes: `getAnnounceScope`, `postAnnouncement`, `listAnnouncements`, `getAnnouncementRecipients` and their types from Task 4's `frontend/src/api/announcements.ts`; `queryKeys.announceScope/announcementsList/announcementRecipients` from Task 4; `HierarchyNodePickerModal` (existing, `frontend/src/components/HierarchyNodePickerModal.tsx`) whose `onPicked` prop this task upgrades to `(nodeId: string, nodeName: string) => void` (see Step 0 — there are currently zero other consumers of this component, verified via `grep -rln "HierarchyNodePickerModal" frontend/src --include=*.tsx`, so this is a safe, non-breaking signature change); `useAuth()` from `frontend/src/auth/AuthContext` (existing, exposes `user.role`, `user.is_commander`, `user.is_duty_manager` — mirror the exact expression `user?.role === "admin" || user?.is_commander || user?.is_duty_manager` already used in `UnifiedNav.tsx`).
- Produces: nothing further downstream (leaf page).

- [ ] **Step 0: Upgrade `HierarchyNodePickerModal` to also return the picked node's name**

In `frontend/src/components/HierarchyNodePickerModal.tsx`, change the `Props` interface:

```typescript
interface Props {
  onClose: () => void;
  onPicked: (nodeId: string, nodeName: string) => void;
}
```

And find the button that calls `onPicked(n.id)`:

```typescript
              <button
                type="button"
                className="text-indigo-600 hover:underline text-xs"
                onClick={() => onPicked(n.id)}
              >
                בחר
              </button>
```

Change it to pass the name too:

```typescript
              <button
                type="button"
                className="text-indigo-600 hover:underline text-xs"
                onClick={() => onPicked(n.id, n.name)}
              >
                בחר
              </button>
```

Run `npm run typecheck` after this change (from `frontend/`) — it should still pass since there are no other current callers of this component to update.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/AnnouncementsPage.test.tsx`:

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import AnnouncementsPage from "./AnnouncementsPage";
import * as announcementsApi from "../api/announcements";
import { useAuth } from "../auth/AuthContext";

vi.mock("../api/announcements");
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../auth/AuthContext");

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AnnouncementsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(announcementsApi.listAnnouncements).mockResolvedValue({ items: [], total: 0 });
});

describe("AnnouncementsPage — commander/DM (scoped)", () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "u1", role: "duty_manager", is_commander: false, is_duty_manager: true },
    } as ReturnType<typeof useAuth>);
    vi.mocked(announcementsApi.getAnnounceScope).mockResolvedValue([
      { id: "node-1", name: "יחידה א", level: "unit" },
    ]);
  });

  it("defaults to sending to the caller's whole scope and submits with that node id", async () => {
    vi.mocked(announcementsApi.postAnnouncement).mockResolvedValue({ id: "ann-1", sent: 5 });
    renderPage();
    await waitFor(() => expect(announcementsApi.getAnnounceScope).toHaveBeenCalled());
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("כותרת"), "בדיקה");
    await user.click(screen.getByRole("button", { name: "שלח הכרזה" }));
    await waitFor(() =>
      expect(announcementsApi.postAnnouncement).toHaveBeenCalledWith({
        title: "בדיקה",
        body: undefined,
        hierarchy_node_ids: ["node-1"],
      })
    );
  });
});

describe("AnnouncementsPage — admin (org-wide default)", () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "u2", role: "admin", is_commander: false, is_duty_manager: false },
    } as ReturnType<typeof useAuth>);
  });

  it("submits with no hierarchy_node_ids by default", async () => {
    vi.mocked(announcementsApi.postAnnouncement).mockResolvedValue({ id: "ann-2", sent: 42 });
    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("כותרת"), "הודעה לכולם");
    await user.click(screen.getByRole("button", { name: "שלח הכרזה" }));
    await waitFor(() =>
      expect(announcementsApi.postAnnouncement).toHaveBeenCalledWith({
        title: "הודעה לכולם",
        body: undefined,
        hierarchy_node_ids: undefined,
      })
    );
  });
});

describe("AnnouncementsPage — history list", () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "u2", role: "admin", is_commander: false, is_duty_manager: false },
    } as ReturnType<typeof useAuth>);
  });

  it("shows sent announcements with read/recipient counts", async () => {
    vi.mocked(announcementsApi.listAnnouncements).mockResolvedValue({
      items: [{
        id: "ann-3", title: "עדכון", body: null, type: "system_announcement",
        hierarchy_node_ids: null, recipient_count: 10, read_count: 3,
        created_at: new Date().toISOString(),
      }],
      total: 1,
    });
    renderPage();
    expect(await screen.findByText("עדכון")).toBeInTheDocument();
    expect(screen.getByText("3 מתוך 10 קראו")).toBeInTheDocument();
  });

  it("fetches and displays recipients when expanded", async () => {
    vi.mocked(announcementsApi.listAnnouncements).mockResolvedValue({
      items: [{
        id: "ann-4", title: "עדכון 2", body: null, type: "announcement",
        hierarchy_node_ids: ["node-1"], recipient_count: 1, read_count: 0,
        created_at: new Date().toISOString(),
      }],
      total: 1,
    });
    vi.mocked(announcementsApi.getAnnouncementRecipients).mockResolvedValue([
      { soldier_id: "s1", full_name: "דני כהן", is_read: false, read_at: null },
    ]);
    renderPage();
    await screen.findByText("עדכון 2");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "הצג נמענים" }));
    expect(await screen.findByText("דני כהן")).toBeInTheDocument();
    expect(screen.getByText("לא נקרא")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npx vitest run src/pages/AnnouncementsPage.test.tsx
```
Expected: FAIL — `./AnnouncementsPage` doesn't exist yet.

- [ ] **Step 3: Write the page**

Create `frontend/src/pages/AnnouncementsPage.tsx`:

```typescript
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Layout from "../components/Layout";
import HierarchyNodePickerModal from "../components/HierarchyNodePickerModal";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";
import {
  getAnnounceScope,
  postAnnouncement,
  listAnnouncements,
  getAnnouncementRecipients,
} from "../api/announcements";

export default function AnnouncementsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const isAdmin = user?.role === "admin";

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [narrowNodeIds, setNarrowNodeIds] = useState<string[]>([]);
  const [narrowNames, setNarrowNames] = useState<Record<string, string>>({});
  const [pickerOpen, setPickerOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const limit = 20;

  const scopeQuery = useQuery({
    queryKey: queryKeys.announceScope(),
    queryFn: getAnnounceScope,
    enabled: !isAdmin,
  });
  const scopeNodes = scopeQuery.data ?? [];

  const historyQuery = useQuery({
    queryKey: queryKeys.announcementsList(offset),
    queryFn: () => listAnnouncements({ offset, limit }),
  });
  const history = historyQuery.data?.items ?? [];
  const total = historyQuery.data?.total ?? 0;

  const recipientsQuery = useQuery({
    queryKey: queryKeys.announcementRecipients(expandedId ?? ""),
    queryFn: () => getAnnouncementRecipients(expandedId as string),
    enabled: expandedId !== null,
  });

  async function handleSubmit() {
    setSubmitting(true);
    setSuccessMsg(null);
    try {
      const hierarchy_node_ids = isAdmin
        ? (narrowNodeIds.length > 0 ? narrowNodeIds : undefined)
        : (scopeNodes.length > 0 ? scopeNodes.map((n) => n.id) : undefined);
      await postAnnouncement({ title, body: body || undefined, hierarchy_node_ids });
      setSuccessMsg(t("announcements.sent_success"));
      setTitle("");
      setBody("");
      setNarrowNodeIds([]);
      setNarrowNames({});
      setOffset(0);
      await queryClient.invalidateQueries({ queryKey: ["notifications", "announcements"] });
    } finally {
      setSubmitting(false);
    }
  }

  function handlePicked(nodeId: string, nodeName: string) {
    setNarrowNodeIds((prev) => (prev.includes(nodeId) ? prev : [...prev, nodeId]));
    setNarrowNames((prev) => ({ ...prev, [nodeId]: nodeName }));
    setPickerOpen(false);
  }

  const pages = Math.ceil(total / limit);
  const typeIcon = (type: string) => (type === "system_announcement" ? "📣" : "📢");

  return (
    <Layout>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mb-6">
        <h2 className="text-xl font-semibold mb-4">{t("announcements.compose_title")}</h2>
        <div className="space-y-3">
          <div>
            <label htmlFor="announcement-title" className="block text-sm text-gray-600 dark:text-gray-300 mb-1">
              {t("announcements.field_title")}
            </label>
            <input
              id="announcement-title"
              aria-label={t("announcements.field_title")}
              className="border rounded p-2 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="announcement-body" className="block text-sm text-gray-600 dark:text-gray-300 mb-1">
              {t("announcements.field_body")}
            </label>
            <textarea
              id="announcement-body"
              aria-label={t("announcements.field_body")}
              className="border rounded p-2 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </div>

          <div>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-1">{t("announcements.target_label")}</p>
            {isAdmin ? (
              <div className="space-y-2">
                <p className="text-sm">
                  {narrowNodeIds.length === 0 ? t("announcements.target_everyone") : Object.values(narrowNames).join(", ")}
                </p>
                <button
                  type="button"
                  className="text-xs text-indigo-600 hover:underline"
                  onClick={() => setPickerOpen(true)}
                >
                  {t("announcements.target_narrow")}
                </button>
                {narrowNodeIds.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className="ms-2 text-xs text-red-500 hover:underline"
                    onClick={() => setNarrowNodeIds((prev) => prev.filter((n) => n !== id))}
                  >
                    {narrowNames[id]} ✕
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-sm">{t("announcements.target_my_scope")}</p>
            )}
          </div>

          {successMsg && <p className="text-sm text-green-600">{successMsg}</p>}

          <button
            type="button"
            disabled={submitting || !title.trim()}
            onClick={handleSubmit}
            className="bg-indigo-600 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
          >
            {submitting ? t("announcements.submitting") : t("announcements.submit")}
          </button>
        </div>
      </div>

      {pickerOpen && (
        <HierarchyNodePickerModal
          onClose={() => setPickerOpen(false)}
          onPicked={handlePicked}
        />
      )}

      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold mb-4">{t("announcements.history_title")}</h2>
        {history.length === 0 ? (
          <p className="text-gray-500">{t("announcements.no_history")}</p>
        ) : (
          <div className="space-y-2">
            {history.map((a) => (
              <div key={a.id} className="border dark:border-gray-600 rounded p-3">
                <div className="flex items-start gap-2">
                  <span className="text-lg">{typeIcon(a.type)}</span>
                  <div className="flex-1">
                    <p className="font-medium">{a.title}</p>
                    {a.body && <p className="text-sm text-gray-500 dark:text-gray-400">{a.body}</p>}
                    <p className="text-xs text-gray-400 mt-1">
                      {t("announcements.read_count", { read: a.read_count, total: a.recipient_count })}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="text-xs text-indigo-600 hover:underline"
                    onClick={() => setExpandedId(expandedId === a.id ? null : a.id)}
                  >
                    {expandedId === a.id ? t("announcements.hide_recipients") : t("announcements.view_recipients")}
                  </button>
                </div>
                {expandedId === a.id && (
                  <div className="mt-2 ps-8 space-y-1">
                    {(recipientsQuery.data ?? []).map((r) => (
                      <div key={r.soldier_id} className="text-sm flex justify-between">
                        <span>{r.full_name}</span>
                        <span className={r.is_read ? "text-green-600" : "text-gray-400"}>
                          {r.is_read ? t("announcements.recipient_read") : t("announcements.recipient_unread")}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
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
    </Layout>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
npx vitest run src/pages/AnnouncementsPage.test.tsx
```
Expected: PASS. If the "defaults to sending to the caller's whole scope" test fails because `scopeNodes` hasn't loaded before submit, that's a real race — the test already `await waitFor(() => expect(announcementsApi.getAnnounceScope).toHaveBeenCalled())` before submitting, which should be enough since `useQuery` resolves the mock promise on the next microtask tick and React re-renders before the click fires; if it's still flaky, add `await waitFor(() => expect(screen.getByText("יחידה א")).toBeInTheDocument())` — but note the current page doesn't render scope node names for non-admin (Step 3 only shows `target_my_scope` text), so instead wait on `scopeQuery` indirectly via a short `await new Promise((r) => setTimeout(r, 0))` is NOT an acceptable pattern (condition-based waiting only) — use `await waitFor(() => expect(announcementsApi.getAnnounceScope).toHaveBeenCalled())` which is already present; that's sufficient since React Query's `useQuery` result is read fresh on every render and the mocked promise resolves in a microtask before `userEvent.type` produces enough renders to proceed to the click.

- [ ] **Step 5: Register the route in App.tsx**

In `frontend/src/App.tsx`, add the import right after `import NotificationsPage from "./pages/NotificationsPage";`:

```typescript
import AnnouncementsPage from "./pages/AnnouncementsPage";
```

Add the route right after `<Route path="/notifications" element={<AppGate><NotificationsPage /></AppGate>} />`:

```typescript
                <Route path="/announcements" element={<AppGate><AnnouncementsPage /></AppGate>} />
```

- [ ] **Step 6: Add the nav entry**

In `frontend/src/components/UnifiedNav.tsx`, find:

```typescript
  const commanderItems = [
    { label: t("nav.team_hierarchy"), to: "/team", testId: "nav-team" },
    { label: t("nav.approvals"), to: "/approvals", badge: pendingCount, testId: "nav-approvals" },
    { label: t("nav.command_dashboard"), to: "/command-dashboard", testId: "nav-command-dashboard" },
    ...(hakpazaEnabled
      ? [{ label: "הקפצה פיקודית", to: "/commander/hakpaza", testId: "nav-hakpaza" }]
      : []),
  ];
```

Add a new entry right after `command_dashboard`:

```typescript
  const commanderItems = [
    { label: t("nav.team_hierarchy"), to: "/team", testId: "nav-team" },
    { label: t("nav.approvals"), to: "/approvals", badge: pendingCount, testId: "nav-approvals" },
    { label: t("nav.command_dashboard"), to: "/command-dashboard", testId: "nav-command-dashboard" },
    { label: t("nav.announcements"), to: "/announcements", testId: "nav-announcements" },
    ...(hakpazaEnabled
      ? [{ label: "הקפצה פיקודית", to: "/commander/hakpaza", testId: "nav-hakpaza" }]
      : []),
  ];
```

- [ ] **Step 7: Run the full frontend suite**

```bash
npx vitest run
```
Expected: all tests pass (including `AnnouncementsPage.test.tsx` and everything from earlier tasks).

- [ ] **Step 8: Run lint and typecheck**

```bash
npm run lint
npm run typecheck
```
Expected: zero warnings/errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/AnnouncementsPage.tsx frontend/src/pages/AnnouncementsPage.test.tsx frontend/src/App.tsx frontend/src/components/UnifiedNav.tsx
git commit -m "feat: add Announcements compose/history page and nav entry"
```

---

### Task 6: End-to-end verification

**Files:** none (verification only).

**Interfaces:** none.

- [ ] **Step 1: Full backend suite**

```bash
cd backend
pytest -q
```
Expected: all pass, same 3 pre-existing solver skips as before this feature, zero failures.

- [ ] **Step 2: Full frontend suite**

```bash
cd frontend
npm test
npm run lint
npm run typecheck
```
Expected: all green.

- [ ] **Step 3: Manual smoke test via the dev server**

Start the stack (`./dev.ps1` from repo root), then in a browser:
1. Log in as an admin. Go to `/announcements`. Confirm the compose form defaults to "כלל הארגון" (org-wide) with no picker required. Submit a test announcement. Then click "בחר יחידה ספציפית", pick a unit from the modal, confirm a chip with the unit's real name (not a raw UUID) appears, and submit a second announcement — confirm only soldiers under that unit receive it.
2. Confirm it appears in the history list below with `recipient_count` matching the number of soldiers in the system, and `read_count` starting at 0.
3. Click "הצג נמענים" and confirm the recipient list appears with everyone marked "לא נקרא".
4. Log in as a different soldier who received it. Confirm the notification bell shows it with the 📣 icon (since it was org-wide).
5. Mark it read. Log back in as the admin, refresh `/announcements`, expand recipients again, confirm that soldier now shows "נקרא" with a `read_at` implied (badge changed).
6. Log in as a commander or duty manager. Go to `/announcements`. Confirm the target defaults to "כל מי שתחת פיקודי" with no extra clicks, submit one, and confirm recipients under their node receive it with the 📢 icon (not 📣).

- [ ] **Step 4: Report results**

Summarize pass/fail for each of the above steps back to the user before considering the feature complete.
