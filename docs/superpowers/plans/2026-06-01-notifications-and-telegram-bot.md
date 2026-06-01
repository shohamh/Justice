# Notifications + Telegram Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add database models, service layer, API routes, frontend components, and a standalone Telegram bot to deliver in-app + push notifications.

**Architecture:** Notification creation called inline from services (like audit writer). `telegram_outbox` queue decouples creation from bot delivery. Frontend polls every 30s. Bot is standalone `python-telegram-bot` with long-polling.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, React 18, Axios, TanStack Query, python-telegram-bot v20+

---

## File Structure

### Backend — New
- `app/services/notifications.py`
- `app/routes/notifications.py`
- `bot/__init__.py`
- `bot/main.py`
- `bot/handlers.py`
- `bot/outbox.py`

### Backend — Modified
- `app/db/models.py`
- `app/settings.py`
- `app/main.py`
- `alembic/versions/0026_notifications.py`

### Backend — Tests
- `tests/integration/test_notifications_api.py`

### Frontend — New
- `src/api/notifications.ts`
- `src/api/telegram.ts`
- `src/components/NotificationBell.tsx`
- `src/pages/NotificationsPage.tsx`

### Frontend — Modified
- `src/components/Layout.tsx`
- `src/pages/ProfilePage.tsx`
- `src/App.tsx`
- `src/i18n/he.json`

---

### Task 1: Database models

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/0026_notifications.py`

- [ ] **Step 1: Add import and 5 new model classes to `models.py`**

Add `import enum as _enum` at the top. Append before the file ends:

```python
class NotificationType(str, _enum.Enum):
    swap_offer = "swap_offer"
    swap_accepted = "swap_accepted"
    swap_rejected = "swap_rejected"
    exemption_approved = "exemption_approved"
    exemption_rejected = "exemption_rejected"
    constraint_approved = "constraint_approved"
    constraint_rejected = "constraint_rejected"
    assignment_created = "assignment_created"
    assignment_removed = "assignment_removed"
    score_adjusted = "score_adjusted"
    announcement = "announcement"


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notification_type"), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    is_read: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)


class TelegramLink(Base):
    __tablename__ = "telegram_links"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False, unique=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, default=None)
    telegram_username: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    verification_code: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    is_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


import sqlalchemy as sa

class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False)
    notification_type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notification_type"), nullable=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    __table_args__ = (sa.UniqueConstraint("soldier_id", "notification_type"),)


class CommanderNotificationScope(Base):
    __tablename__ = "commander_notification_scopes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    commander_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False)
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id"), nullable=False)


class TelegramOutbox(Base):
    __tablename__ = "telegram_outbox"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    telegram_chat_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
```

- [ ] **Step 2: Verify models import cleanly**

```bash
cd backend && python -c "from app.db.models import Notification, TelegramLink, NotificationPreference, CommanderNotificationScope, TelegramOutbox, NotificationType; print('OK')"
```

- [ ] **Step 3: Generate migration**

```bash
cd backend && alembic revision --autogenerate -m "notifications system"
```

- [ ] **Step 4: Run migration**

```bash
cd backend && alembic upgrade head
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0026_notifications.py
git commit -m "feat: add notification system database models"
```

---

### Task 2: Notification service

**Files:**
- Create: `backend/app/services/notifications.py`

- [ ] **Step 1: Write the service**

Create `backend/app/services/notifications.py`:

```python
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    CommanderNotificationScope,
    HierarchyNode,
    Notification,
    NotificationPreference,
    NotificationType,
    Soldier,
    TelegramLink,
    TelegramOutbox,
)


class NotificationError(Exception):
    pass


def create_notification(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> Notification:
    notif = Notification(
        soldier_id=soldier_id, type=type, title=title, body=body,
        reference_type=reference_type, reference_id=reference_id,
    )
    session.add(notif)
    session.flush()
    write_audit(session, actor_id=actor_id, action="notification.create",
                entity_type="notification", entity_id=notif.id,
                after={"soldier_id": str(soldier_id), "type": type.value, "title": title})
    cascade_to_commanders(session, type=type, title=title, body=body,
                          reference_type=reference_type, reference_id=reference_id,
                          actor_id=actor_id, original_soldier_id=soldier_id)
    _enqueue_push(session, soldier_id=soldier_id, text=title)
    return notif


def cascade_to_commanders(session: Session, *, type: NotificationType, title: str,
                          body: str | None, reference_type: str | None,
                          reference_id: uuid.UUID | None, actor_id: uuid.UUID | None,
                          original_soldier_id: uuid.UUID) -> None:
    soldier = session.get(Soldier, original_soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return
    soldier_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if soldier_node is None or not soldier_node.path_ids:
        return
    scopes = session.execute(
        select(CommanderNotificationScope).where(
            CommanderNotificationScope.hierarchy_node_id.in_(soldier_node.path_ids),
        )
    ).scalars().all()
    seen: set[uuid.UUID] = set()
    for scope in scopes:
        if scope.commander_id in seen:
            continue
        seen.add(scope.commander_id)
        _create_notif(session, soldier_id=scope.commander_id,
                      type=type, title=f"{soldier.full_name}: {title}",
                      body=body, reference_type=reference_type,
                      reference_id=reference_id, actor_id=actor_id)


def _create_notif(session: Session, *, soldier_id: uuid.UUID, type: NotificationType,
                  title: str, body: str | None, reference_type: str | None,
                  reference_id: uuid.UUID | None, actor_id: uuid.UUID | None) -> None:
    pref = session.execute(
        select(NotificationPreference).where(
            NotificationPreference.soldier_id == soldier_id,
            NotificationPreference.notification_type == type,
        )
    ).scalar_one_or_none()
    if pref is not None and not pref.in_app_enabled:
        return
    notif = Notification(soldier_id=soldier_id, type=type, title=title, body=body,
                         reference_type=reference_type, reference_id=reference_id)
    session.add(notif)
    _enqueue_push(session, soldier_id=soldier_id, text=title)


def _enqueue_push(session: Session, *, soldier_id: uuid.UUID, text: str) -> None:
    link = session.execute(
        select(TelegramLink).where(
            TelegramLink.soldier_id == soldier_id,
            TelegramLink.is_verified == True,
            TelegramLink.notifications_enabled == True,
            TelegramLink.telegram_chat_id.isnot(None),
        )
    ).scalar_one_or_none()
    if link is None:
        return
    session.add(TelegramOutbox(telegram_chat_id=link.telegram_chat_id, message_text=text))


def ensure_default_prefs(session: Session, *, soldier_id: uuid.UUID) -> None:
    existing = set(
        session.execute(
            select(NotificationPreference.notification_type).where(
                NotificationPreference.soldier_id == soldier_id,
            )
        ).scalars().all()
    )
    for nt in NotificationType:
        if nt not in existing:
            session.add(NotificationPreference(
                soldier_id=soldier_id, notification_type=nt,
                in_app_enabled=True, push_enabled=False,
            ))


def get_preferences(session: Session, *, soldier_id: uuid.UUID) -> list[NotificationPreference]:
    ensure_default_prefs(session, soldier_id=soldier_id)
    return list(session.execute(
        select(NotificationPreference).where(NotificationPreference.soldier_id == soldier_id)
        .order_by(NotificationPreference.notification_type)
    ).scalars().all())


def update_preferences(session: Session, *, soldier_id: uuid.UUID,
                       preferences: list[dict]) -> list[NotificationPreference]:
    ensure_default_prefs(session, soldier_id=soldier_id)
    for pd in preferences:
        pref = session.execute(
            select(NotificationPreference).where(
                NotificationPreference.soldier_id == soldier_id,
                NotificationPreference.notification_type == NotificationType(pd["notification_type"]),
            )
        ).scalar_one_or_none()
        if pref:
            pref.in_app_enabled = pd.get("in_app_enabled", pref.in_app_enabled)
            pref.push_enabled = pd.get("push_enabled", pref.push_enabled)
    return get_preferences(session, soldier_id=soldier_id)


def generate_code(session: Session, *, soldier_id: uuid.UUID) -> tuple[str, datetime]:
    code = secrets.token_hex(3).upper()[:6]
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    existing = session.execute(
        select(TelegramLink).where(TelegramLink.soldier_id == soldier_id)
    ).scalar_one_or_none()
    if existing:
        existing.verification_code = code
        existing.verification_expires_at = expires_at
        existing.is_verified = False
    else:
        session.add(TelegramLink(soldier_id=soldier_id, verification_code=code,
                                  verification_expires_at=expires_at))
    return code, expires_at


def telegram_status(session: Session, *, soldier_id: uuid.UUID) -> dict | None:
    link = session.execute(
        select(TelegramLink).where(TelegramLink.soldier_id == soldier_id)
    ).scalar_one_or_none()
    if link is None:
        return None
    return {"is_verified": link.is_verified, "telegram_username": link.telegram_username,
            "created_at": link.created_at.isoformat() if link.created_at else None,
            "verified_at": link.verified_at.isoformat() if link.verified_at else None}


def unlink_telegram(session: Session, *, soldier_id: uuid.UUID) -> None:
    link = session.execute(
        select(TelegramLink).where(TelegramLink.soldier_id == soldier_id)
    ).scalar_one_or_none()
    if link:
        link.telegram_chat_id = None
        link.telegram_username = None
        link.is_verified = False
        link.verified_at = None
        link.notifications_enabled = True


def list_notifications(session: Session, *, soldier_id: uuid.UUID,
                       is_read: bool | None = None, type: str | None = None,
                       offset: int = 0, limit: int = 20) -> tuple[list[Notification], int]:
    q = select(Notification).where(Notification.soldier_id == soldier_id)
    if is_read is not None:
        q = q.where(Notification.is_read == is_read)
    if type is not None:
        q = q.where(Notification.type == NotificationType(type))
    total = len(session.execute(q.with_only_columns(Notification.id)).scalars().all())
    results = list(session.execute(q.order_by(Notification.created_at.desc()).offset(offset).limit(limit)).scalars().all())
    return results, total


def unread_count(session: Session, *, soldier_id: uuid.UUID) -> int:
    return len(session.execute(
        select(Notification.id).where(Notification.soldier_id == soldier_id, Notification.is_read == False)
    ).scalars().all())


def mark_read(session: Session, *, notification_id: uuid.UUID, soldier_id: uuid.UUID) -> Notification | None:
    n = session.execute(select(Notification).where(Notification.id == notification_id, Notification.soldier_id == soldier_id)).scalar_one_or_none()
    if n:
        n.is_read = True
    return n


def mark_all_read(session: Session, *, soldier_id: uuid.UUID) -> int:
    notifs = list(session.execute(select(Notification).where(Notification.soldier_id == soldier_id, Notification.is_read == False)).scalars().all())
    for n in notifs:
        n.is_read = True
    return len(notifs)


def delete_notification(session: Session, *, notification_id: uuid.UUID, soldier_id: uuid.UUID) -> bool:
    n = session.execute(select(Notification).where(Notification.id == notification_id, Notification.soldier_id == soldier_id)).scalar_one_or_none()
    if n:
        session.delete(n)
        return True
    return False


def list_commander_scopes(session: Session, *, commander_id: uuid.UUID) -> list[CommanderNotificationScope]:
    return list(session.execute(
        select(CommanderNotificationScope).where(CommanderNotificationScope.commander_id == commander_id)
    ).scalars().all())


def add_commander_scope(session: Session, *, commander_id: uuid.UUID, hierarchy_node_id: uuid.UUID) -> CommanderNotificationScope:
    s = CommanderNotificationScope(commander_id=commander_id, hierarchy_node_id=hierarchy_node_id)
    session.add(s)
    session.flush()
    return s


def remove_commander_scope(session: Session, *, scope_id: uuid.UUID, commander_id: uuid.UUID) -> bool:
    s = session.execute(select(CommanderNotificationScope).where(CommanderNotificationScope.id == scope_id, CommanderNotificationScope.commander_id == commander_id)).scalar_one_or_none()
    if s:
        session.delete(s)
        return True
    return False


def broadcast_announcement(session: Session, *, title: str, body: str | None = None,
                           hierarchy_node_ids: list[uuid.UUID] | None = None,
                           actor_id: uuid.UUID | None = None) -> int:
    if hierarchy_node_ids:
        nodes = session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(hierarchy_node_ids))).scalars().all()
        path_sets = [set(n.path_ids) for n in nodes if n.path_ids]
        all_nodes = session.execute(select(HierarchyNode)).scalars().all()
        target_soldier_ids = set()
        for node in all_nodes:
            if any(p in node.path_ids for p in set().union(*path_sets) if path_sets):
                target_soldier_ids.add(node.id)
        soldiers = session.execute(select(Soldier).where(Soldier.hierarchy_node_id.in_(target_soldier_ids))).scalars().all() if target_soldier_ids else []
    else:
        soldiers = session.execute(select(Soldier)).scalars().all()
    count = 0
    for s in soldiers:
        create_notification(session, soldier_id=s.id, type=NotificationType.announcement, title=title, body=body, actor_id=actor_id)
        count += 1
    return count
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/notifications.py
git commit -m "feat: add notification service"
```

---

### Task 3: Settings + main.py wiring

- [ ] **Step 1: Add bot token settings to `settings.py`**

```python
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")
```

- [ ] **Step 2: Register notifications router in `main.py`**

```python
from app.routes import notifications as notification_routes
# ...
app.include_router(notification_routes.router, prefix="/api")
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/settings.py backend/app/main.py
git commit -m "feat: wire up notification settings and router"
```

---

### Task 4: Notification API routes

**Files:**
- Create: `backend/app/routes/notifications.py`

- [ ] **Step 1: Write routes**

```python
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import CommanderNotificationScope, Notification, NotificationPreference, NotificationType, Soldier
from app.db.session import get_session
from app.services import notifications as svc

router = APIRouter(tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    title: str
    body: str | None
    type: str
    reference_type: str | None
    reference_id: uuid.UUID | None
    is_read: bool
    created_at: datetime


class NotificationPrefOut(BaseModel):
    notification_type: str
    in_app_enabled: bool
    push_enabled: bool


class UpdatePrefsBody(BaseModel):
    preferences: list[dict]


class TelegramStatusOut(BaseModel):
    is_verified: bool
    telegram_username: str | None = None
    created_at: str | None = None
    verified_at: str | None = None


class GenerateCodeOut(BaseModel):
    code: str
    expires_at: datetime


class CommanderScopeOut(BaseModel):
    id: uuid.UUID
    hierarchy_node_id: uuid.UUID


class AddScopeBody(BaseModel):
    hierarchy_node_id: uuid.UUID


class AnnounceBody(BaseModel):
    title: str
    body: str | None = None
    hierarchy_node_ids: list[uuid.UUID] | None = None


class PaginatedNotifications(BaseModel):
    items: list[NotificationOut]
    total: int


class UnreadCountOut(BaseModel):
    count: int


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id, soldier_id=n.soldier_id, title=n.title, body=n.body,
        type=n.type.value, reference_type=n.reference_type,
        reference_id=n.reference_id, is_read=n.is_read, created_at=n.created_at,
    )


def _err(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


@router.get("/notifications", response_model=PaginatedNotifications)
def list_my_notifications(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
    is_read: bool | None = None,
    type: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> PaginatedNotifications:
    items, total = svc.list_notifications(session, soldier_id=user.id,
                                           is_read=is_read, type=type,
                                           offset=offset, limit=limit)
    return PaginatedNotifications(items=[_out(n) for n in items], total=total)


@router.get("/notifications/unread-count", response_model=UnreadCountOut)
def unread_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> UnreadCountOut:
    return UnreadCountOut(count=svc.unread_count(session, soldier_id=user.id))


@router.patch("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NotificationOut:
    n = svc.mark_read(session, notification_id=notification_id, soldier_id=user.id)
    if n is None:
        raise _err("not_found", 404)
    session.commit()
    return _out(n)


@router.patch("/notifications/read-all", response_model=UnreadCountOut)
def mark_all_read(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> UnreadCountOut:
    count = svc.mark_all_read(session, soldier_id=user.id)
    session.commit()
    return UnreadCountOut(count=count)


@router.delete("/notifications/{notification_id}", status_code=204)
def delete_notification(
    notification_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    if not svc.delete_notification(session, notification_id=notification_id, soldier_id=user.id):
        raise _err("not_found", 404)
    session.commit()


@router.get("/notifications/preferences", response_model=list[NotificationPrefOut])
def get_preferences(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NotificationPrefOut]:
    prefs = svc.get_preferences(session, soldier_id=user.id)
    return [NotificationPrefOut(notification_type=p.notification_type.value,
                                 in_app_enabled=p.in_app_enabled, push_enabled=p.push_enabled)
            for p in prefs]


@router.put("/notifications/preferences", response_model=list[NotificationPrefOut])
def update_preferences(
    body: UpdatePrefsBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NotificationPrefOut]:
    prefs = svc.update_preferences(session, soldier_id=user.id, preferences=body.preferences)
    session.commit()
    return [NotificationPrefOut(notification_type=p.notification_type.value,
                                 in_app_enabled=p.in_app_enabled, push_enabled=p.push_enabled)
            for p in prefs]


@router.get("/notifications/commander-scopes", response_model=list[CommanderScopeOut])
def list_scopes(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[CommanderScopeOut]:
    authorize(session, user, Action.SOLDIER_READ, target_node=None)
    scopes = svc.list_commander_scopes(session, commander_id=user.id)
    return [CommanderScopeOut(id=s.id, hierarchy_node_id=s.hierarchy_node_id) for s in scopes]


@router.post("/notifications/commander-scopes", response_model=CommanderScopeOut, status_code=201)
def add_scope(
    body: AddScopeBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CommanderScopeOut:
    authorize(session, user, Action.SOLDIER_READ, target_node=None)
    scope = svc.add_commander_scope(session, commander_id=user.id,
                                     hierarchy_node_id=body.hierarchy_node_id)
    session.commit()
    return CommanderScopeOut(id=scope.id, hierarchy_node_id=scope.hierarchy_node_id)


@router.delete("/notifications/commander-scopes/{scope_id}", status_code=204)
def remove_scope(
    scope_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    authorize(session, user, Action.SOLDIER_READ, target_node=None)
    if not svc.remove_commander_scope(session, scope_id=scope_id, commander_id=user.id):
        raise _err("not_found", 404)
    session.commit()


@router.post("/notifications/announce", status_code=201)
def announce(
    body: AnnounceBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    count = svc.broadcast_announcement(session, title=body.title, body=body.body,
                                        hierarchy_node_ids=body.hierarchy_node_ids,
                                        actor_id=user.id)
    session.commit()
    return {"sent": count}


@router.post("/telegram/link", response_model=GenerateCodeOut)
def generate_code(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> GenerateCodeOut:
    code, expires_at = svc.generate_code(session, soldier_id=user.id)
    session.commit()
    return GenerateCodeOut(code=code, expires_at=expires_at)


@router.get("/telegram/link/status", response_model=TelegramStatusOut)
def link_status(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TelegramStatusOut:
    status = svc.telegram_status(session, soldier_id=user.id)
    if status is None:
        return TelegramStatusOut(is_verified=False)
    return TelegramStatusOut(**status)


@router.delete("/telegram/link", status_code=204)
def unlink(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    svc.unlink_telegram(session, soldier_id=user.id)
    session.commit()
```

- [ ] **Step 2: Verify routes import**

```bash
cd backend && python -c "from app.routes.notifications import router; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/notifications.py
git commit -m "feat: add notification and telegram API routes"
```

---

### Task 5: Integration tests

**Files:**
- Create: `backend/tests/integration/test_notifications_api.py`

- [ ] **Step 1: Write tests**

```python
import uuid

from app.db.models import Notification, NotificationPreference, NotificationType, TelegramLink


def test_unread_count_zero(client, test_soldier):
    resp = client.get("/api/notifications/unread-count")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_create_notification_via_service(client, test_soldier, session):
    from app.services.notifications import create_notification
    create_notification(session, soldier_id=test_soldier.id,
                        type=NotificationType.announcement, title="Test", body="Hello",
                        actor_id=test_soldier.id)
    session.commit()
    resp = client.get("/api/notifications/unread-count")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_list_notifications(client, test_soldier, session):
    from app.services.notifications import create_notification
    create_notification(session, soldier_id=test_soldier.id,
                        type=NotificationType.swap_accepted, title="Swap OK", actor_id=test_soldier.id)
    session.commit()
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Swap OK"
    assert data["items"][0]["type"] == "swap_accepted"
    assert data["items"][0]["is_read"] is False


def test_mark_read(client, test_soldier, session):
    from app.services.notifications import create_notification
    n = create_notification(session, soldier_id=test_soldier.id,
                            type=NotificationType.announcement, title="Read me", actor_id=test_soldier.id)
    session.commit()
    resp = client.patch(f"/api/notifications/{n.id}/read")
    assert resp.status_code == 200
    assert resp.json()["is_read"] is True


def test_mark_all_read(client, test_soldier, session):
    from app.services.notifications import create_notification
    for i in range(3):
        create_notification(session, soldier_id=test_soldier.id,
                            type=NotificationType.announcement, title=f"N{i}", actor_id=test_soldier.id)
    session.commit()
    resp = client.patch("/api/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json()["count"] == 3


def test_delete_notification(client, test_soldier, session):
    from app.services.notifications import create_notification
    n = create_notification(session, soldier_id=test_soldier.id,
                            type=NotificationType.announcement, title="Delete me", actor_id=test_soldier.id)
    session.commit()
    resp = client.delete(f"/api/notifications/{n.id}")
    assert resp.status_code == 204


def test_preferences_defaults(client, test_soldier):
    resp = client.get("/api/notifications/preferences")
    assert resp.status_code == 200
    prefs = resp.json()
    assert len(prefs) == len(NotificationType)
    for p in prefs:
        assert p["in_app_enabled"] is True
        assert p["push_enabled"] is False


def test_update_preferences(client, test_soldier):
    resp = client.put("/api/notifications/preferences", json={
        "preferences": [{"notification_type": "announcement", "in_app_enabled": False, "push_enabled": True}]
    })
    assert resp.status_code == 200
    updated = {p["notification_type"]: p for p in resp.json()}
    assert updated["announcement"]["in_app_enabled"] is False
    assert updated["announcement"]["push_enabled"] is True


def test_telegram_generate_code(client, test_soldier, session):
    resp = client.post("/api/telegram/link")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["code"]) == 6
    assert data["expires_at"] is not None


def test_telegram_link_status_unlinked(client, test_soldier):
    resp = client.get("/api/telegram/link/status")
    assert resp.status_code == 200
    assert resp.json()["is_verified"] is False


def test_telegram_unlink(client, test_soldier, session):
    from app.services.notifications import generate_code
    generate_code(session, soldier_id=test_soldier.id)
    session.commit()
    resp = client.delete("/api/telegram/link")
    assert resp.status_code == 204


def test_commander_scopes(client, test_soldier, session, test_hierarchy):
    resp = client.post("/api/notifications/commander-scopes", json={
        "hierarchy_node_id": str(test_hierarchy.id)
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["hierarchy_node_id"] == str(test_hierarchy.id)
    resp2 = client.get("/api/notifications/commander-scopes")
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1
```

- [ ] **Step 2: Run tests**

```bash
cd backend && python -m pytest tests/integration/test_notifications_api.py -v
```

If the test helpers don't expose `test_hierarchy` in conftest, check conftest.py for available fixtures and adjust the test accordingly.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_notifications_api.py
git commit -m "test: add notification API integration tests"
```

---

### Task 6: Telegram bot

**Files:**
- Create: `backend/bot/__init__.py` (empty)
- Create: `backend/bot/main.py`
- Create: `backend/bot/handlers.py`
- Create: `backend/bot/outbox.py`

- [ ] **Step 1: Write bot main entry**

`backend/bot/main.py`:
```python
from __future__ import annotations

import asyncio
import logging

from telegram import Bot
from telegram.ext import Application, CommandHandler

from app.settings import get_settings
from bot.handlers import start, verify, status, unlink, help_command
from bot.outbox import poll_outbox

logger = logging.getLogger(__name__)


async def outbox_loop(app: Application) -> None:
    while True:
        try:
            await poll_outbox(app.bot)
        except Exception:
            logger.exception("outbox poll failed")
        await asyncio.sleep(2)


def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set; bot not starting")
        return

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("unlink", unlink))
    app.add_handler(CommandHandler("help", help_command))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(outbox_loop(app))
    app.run_polling()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write handlers**

`backend/bot/handlers.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from app.db.session import SessionFactory
from app.db.models import TelegramLink
from sqlalchemy import select


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "ברוכים הבאים! כדי לקשר את חשבון הטלגרם שלך, פתח את האתר, "
        "לחץ על 'קשר חשבון טלגרם' באזור האישי, הזן את הקוד שתראה שם."
    )


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0]:
        await update.message.reply_text("אנא הזן קוד: /verify <קוד>")
        return
    code = context.args[0].strip().upper()
    with SessionFactory() as session:
        link = session.execute(
            select(TelegramLink).where(
                TelegramLink.verification_code == code,
                TelegramLink.is_verified == False,
            )
        ).scalar_one_or_none()
        if link is None or (link.verification_expires_at and link.verification_expires_at < datetime.now(timezone.utc)):
            await update.message.reply_text("קוד לא תקין או שפג תוקפו. אנא צור קוד חדש באתר.")
            return
        link.telegram_chat_id = update.effective_chat.id
        link.telegram_username = update.effective_user.username
        link.is_verified = True
        link.verified_at = datetime.now(timezone.utc)
        link.verification_code = None
        link.verification_expires_at = None
        session.commit()
    await update.message.reply_text("החשבון שלך אומת בהצלחה!")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    with SessionFactory() as session:
        link = session.execute(
            select(TelegramLink).where(TelegramLink.telegram_chat_id == chat_id)
        ).scalar_one_or_none()
    if link and link.is_verified:
        await update.message.reply_text(f"✅ חשבון טלגרם מקושר ל-@{link.telegram_username or '?'}.")
    else:
        await update.message.reply_text("❌ חשבון טלגרם לא מקושר. פתח את האתר לצורך קישור.")


async def unlink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    with SessionFactory() as session:
        link = session.execute(
            select(TelegramLink).where(TelegramLink.telegram_chat_id == chat_id)
        ).scalar_one_or_none()
        if link:
            link.telegram_chat_id = None
            link.telegram_username = None
            link.is_verified = False
            link.verified_at = None
            session.commit()
    await update.message.reply_text("החשבון בוטל בהצלחה.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "/start - הוראות התחלה\n"
        "/verify <קוד> - אימות חשבון טלגרם\n"
        "/status - בדיקת סטטוס חיבור\n"
        "/unlink - ביטול קישור חשבון טלגרם"
    )
```

- [ ] **Step 3: Write outbox poller**

`backend/bot/outbox.py`:
```python
from __future__ import annotations

import logging

from telegram import Bot

from app.db.session import SessionFactory
from app.db.models import TelegramOutbox
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def poll_outbox(bot: Bot) -> None:
    with SessionFactory() as session:
        rows = list(
            session.execute(
                select(TelegramOutbox).where(TelegramOutbox.sent_at.is_(None))
                .order_by(TelegramOutbox.created_at)
                .limit(20)
            ).scalars().all()
        )
        for row in rows:
            try:
                await bot.send_message(chat_id=row.telegram_chat_id, text=row.message_text)
                row.sent_at = __import__("datetime").datetime.now(__import__("pytz").UTC if hasattr(__import__("pytz"), "UTC") else None)
                # simpler:
                from datetime import datetime, timezone
                row.sent_at = datetime.now(timezone.utc)
            except Exception as e:
                logger.warning("failed to send to chat %s: %s", row.telegram_chat_id, e)
                row.error = str(e)
            session.commit()
```

- [ ] **Step 4: Add bot dependency to pyproject.toml**

Add `python-telegram-bot>=20.0,<21.0` to `pyproject.toml` dependencies.

```bash
cd backend && pip install python-telegram-bot
```

- [ ] **Step 5: Commit**

```bash
git add backend/bot/ backend/pyproject.toml
git commit -m "feat: add Telegram bot with verification flow"
```

---

### Task 7: Frontend API clients

**Files:**
- Create: `frontend/src/api/notifications.ts`
- Create: `frontend/src/api/telegram.ts`

- [ ] **Step 1: Create notification API client**

`frontend/src/api/notifications.ts`:
```typescript
import client from "./client";

export interface NotificationDTO {
  id: string;
  soldier_id: string;
  title: string;
  body: string | null;
  type: string;
  reference_type: string | null;
  reference_id: string | null;
  is_read: boolean;
  created_at: string;
}

export interface PaginatedNotifications {
  items: NotificationDTO[];
  total: number;
}

export interface UnreadCount {
  count: number;
}

export interface NotificationPref {
  notification_type: string;
  in_app_enabled: boolean;
  push_enabled: boolean;
}

export interface CommanderScope {
  id: string;
  hierarchy_node_id: string;
}

export function getUnreadCount(): Promise<UnreadCount> {
  return client.get("/notifications/unread-count").then((r) => r.data);
}

export function listNotifications(params?: {
  is_read?: boolean;
  type?: string;
  offset?: number;
  limit?: number;
}): Promise<PaginatedNotifications> {
  return client.get("/notifications", { params }).then((r) => r.data);
}

export function markRead(id: string): Promise<NotificationDTO> {
  return client.patch(`/notifications/${id}/read`).then((r) => r.data);
}

export function markAllRead(): Promise<UnreadCount> {
  return client.patch("/notifications/read-all").then((r) => r.data);
}

export function deleteNotification(id: string): Promise<void> {
  return client.delete(`/notifications/${id}`);
}

export function getPreferences(): Promise<NotificationPref[]> {
  return client.get("/notifications/preferences").then((r) => r.data);
}

export function updatePreferences(preferences: { notification_type: string; in_app_enabled: boolean; push_enabled: boolean }[]): Promise<NotificationPref[]> {
  return client.put("/notifications/preferences", { preferences }).then((r) => r.data);
}

export function listCommanderScopes(): Promise<CommanderScope[]> {
  return client.get("/notifications/commander-scopes").then((r) => r.data);
}

export function addCommanderScope(hierarchy_node_id: string): Promise<CommanderScope> {
  return client.post("/notifications/commander-scopes", { hierarchy_node_id }).then((r) => r.data);
}

export function removeCommanderScope(id: string): Promise<void> {
  return client.delete(`/notifications/commander-scopes/${id}`);
}
```

- [ ] **Step 2: Create Telegram API client**

`frontend/src/api/telegram.ts`:
```typescript
import client from "./client";

export interface GenerateCodeResult {
  code: string;
  expires_at: string;
}

export interface TelegramStatus {
  is_verified: boolean;
  telegram_username?: string | null;
  created_at?: string | null;
  verified_at?: string | null;
}

export function generateTelegramCode(): Promise<GenerateCodeResult> {
  return client.post("/telegram/link").then((r) => r.data);
}

export function getTelegramStatus(): Promise<TelegramStatus> {
  return client.get("/telegram/link/status").then((r) => r.data);
}

export function unlinkTelegram(): Promise<void> {
  return client.delete("/telegram/link");
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/notifications.ts frontend/src/api/telegram.ts
git commit -m "feat: add frontend API clients for notifications and telegram"
```

---

### Task 8: NotificationBell + Layout integration

**Files:**
- Create: `frontend/src/components/NotificationBell.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Create NotificationBell component**

`frontend/src/components/NotificationBell.tsx`:
```tsx
import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getUnreadCount, listNotifications, markRead, markAllRead, deleteNotification, NotificationDTO } from "../api/notifications";

export default function NotificationBell() {
  const { t } = useTranslation();
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationDTO[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fetch = async () => {
      try {
        const { count } = await getUnreadCount();
        setUnread(count);
      } catch { /* ignore */ }
    };
    fetch();
    const interval = setInterval(fetch, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (open) {
      listNotifications({ is_read: false, limit: 5 }).then((r) => setNotifications(r.items)).catch(() => {});
    }
  }, [open]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  async function handleMarkRead(id: string) {
    await markRead(id).catch(() => {});
    setNotifications((prev) => prev.filter((n) => n.id !== id));
    setUnread((u) => Math.max(0, u - 1));
  }

  async function handleDelete(id: string) {
    await deleteNotification(id).catch(() => {});
    setNotifications((prev) => prev.filter((n) => n.id !== id));
    setUnread((u) => Math.max(0, u - 1));
  }

  async function handleMarkAll() {
    const { count } = await markAllRead().catch(() => ({ count: 0 }));
    setUnread(Math.max(0, unread - count));
    setNotifications([]);
  }

  const typeLabels: Record<string, string> = {
    swap_offer: "🔄", swap_accepted: "✅", swap_rejected: "❌",
    exemption_approved: "✔️", exemption_rejected: "✖️",
    constraint_approved: "✔️", constraint_rejected: "✖️",
    assignment_created: "📋", assignment_removed: "🗑️",
    score_adjusted: "⭐", announcement: "📢",
  };

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="relative p-2 rounded hover:bg-gray-100" data-testid="notification-bell">
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute left-0 mt-2 w-80 bg-white rounded-lg shadow-lg border z-50 rtl:text-right" data-testid="notification-dropdown">
          <div className="flex items-center justify-between p-3 border-b">
            <span className="font-semibold">{t("notifications.title")}</span>
            {notifications.length > 0 && (
              <button onClick={handleMarkAll} className="text-xs text-indigo-600 hover:text-indigo-800">
                {t("notifications.mark_all_read")}
              </button>
            )}
          </div>
          <div className="max-h-64 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="p-4 text-center text-gray-500 text-sm">{t("notifications.none")}</div>
            ) : (
              notifications.map((n) => (
                <div key={n.id} className="flex items-start gap-2 p-3 border-b hover:bg-gray-50">
                  <span className="text-lg">{typeLabels[n.type] || "🔔"}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{n.title}</p>
                    {n.body && <p className="text-xs text-gray-500 truncate">{n.body}</p>}
                  </div>
                  <div className="flex gap-1">
                    <button onClick={() => handleMarkRead(n.id)} className="text-xs text-gray-400 hover:text-gray-600" title={t("notifications.mark_read")}>✓</button>
                    <button onClick={() => handleDelete(n.id)} className="text-xs text-gray-400 hover:text-red-600" title={t("notifications.dismiss")}>✕</button>
                  </div>
                </div>
              ))
            )}
          </div>
          <Link to="/notifications" className="block p-3 text-center text-sm text-indigo-600 hover:text-indigo-800 border-t">
            {t("notifications.view_all")}
          </Link>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add NotificationBell to Layout**

In `Layout.tsx`, import and add `<NotificationBell />` inside the header, before the logout button.

```tsx
import NotificationBell from "./NotificationBell";
// ...
<header>
  <div className="px-4 py-3 flex items-center justify-between">
    <h1 className="text-lg font-bold">{t("app.title")}</h1>
    <div className="flex items-center gap-4">
      <NotificationBell />
      <button onClick={() => logout()} className="text-sm text-indigo-600 hover:text-indigo-800" data-testid="logout-button">
        {t("home.logout")}
      </button>
    </div>
  </div>
</header>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/NotificationBell.tsx frontend/src/components/Layout.tsx
git commit -m "feat: add NotificationBell component with dropdown"
```

---

### Task 9: NotificationsPage

**Files:**
- Create: `frontend/src/pages/NotificationsPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create NotificationsPage**

```tsx
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import { listNotifications, markRead, markAllRead, deleteNotification, NotificationDTO } from "../api/notifications";

export default function NotificationsPage() {
  const { t } = useTranslation();
  const [notifications, setNotifications] = useState<NotificationDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<string>("all");
  const [offset, setOffset] = useState(0);
  const limit = 20;

  useEffect(() => {
    const params: Record<string, unknown> = { offset, limit };
    if (filter === "unread") params.is_read = false;
    listNotifications(params).then((r) => {
      setNotifications(r.items);
      setTotal(r.total);
    }).catch(() => {});
  }, [filter, offset]);

  async function handleMarkRead(id: string) {
    await markRead(id);
    setNotifications((prev) => prev.map((n) => n.id === id ? { ...n, is_read: true } : n));
  }

  async function handleMarkAll() {
    const { count } = await markAllRead();
    setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
  }

  async function handleDelete(id: string) {
    await deleteNotification(id);
    setNotifications((prev) => prev.filter((n) => n.id !== id));
    setTotal((t) => t - 1);
  }

  const typeLabels: Record<string, string> = {
    swap_offer: "🔄", swap_accepted: "✅", swap_rejected: "❌",
    exemption_approved: "✔️", exemption_rejected: "✖️",
    constraint_approved: "✔️", constraint_rejected: "✖️",
    assignment_created: "📋", assignment_removed: "🗑️",
    score_adjusted: "⭐", announcement: "📢",
  };

  const pages = Math.ceil(total / limit);

  return (
    <Layout>
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">{t("notifications.title")}</h2>
          <button onClick={handleMarkAll} className="text-sm text-indigo-600 hover:text-indigo-800">
            {t("notifications.mark_all_read")}
          </button>
        </div>
        {total > 0 && (
          <div className="flex gap-2 mb-4">
            <button onClick={() => { setFilter("all"); setOffset(0); }}
                    className={`px-3 py-1 rounded text-sm ${filter === "all" ? "bg-indigo-100 text-indigo-700" : "bg-gray-100"}`}>
              {t("notifications.all")} ({total})
            </button>
            <button onClick={() => { setFilter("unread"); setOffset(0); }}
                    className={`px-3 py-1 rounded text-sm ${filter === "unread" ? "bg-indigo-100 text-indigo-700" : "bg-gray-100"}`}>
              {t("notifications.unread")}
            </button>
          </div>
        )}
        {notifications.length === 0 ? (
          <p className="text-gray-500">{t("notifications.none")}</p>
        ) : (
          <div className="space-y-2">
            {notifications.map((n) => (
              <div key={n.id} className={`flex items-start gap-3 p-3 rounded border ${n.is_read ? "bg-gray-50" : "bg-white"}`}>
                <span className="text-xl">{typeLabels[n.type] || "🔔"}</span>
                <div className="flex-1">
                  <p className={`${n.is_read ? "text-gray-600" : "font-semibold"}`}>{n.title}</p>
                  {n.body && <p className="text-sm text-gray-500">{n.body}</p>}
                  <p className="text-xs text-gray-400 mt-1">{new Date(n.created_at).toLocaleString("he-IL")}</p>
                </div>
                <div className="flex gap-1">
                  {!n.is_read && (
                    <button onClick={() => handleMarkRead(n.id)} className="text-xs text-gray-400 hover:text-indigo-600" title={t("notifications.mark_read")}>
                      ✓
                    </button>
                  )}
                  <button onClick={() => handleDelete(n.id)} className="text-xs text-gray-400 hover:text-red-600" title={t("notifications.dismiss")}>
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        {pages > 1 && (
          <div className="flex justify-center gap-2 mt-4">
            {Array.from({ length: pages }, (_, i) => (
              <button key={i} onClick={() => setOffset(i * limit)}
                      className={`px-3 py-1 rounded text-sm ${offset === i * limit ? "bg-indigo-600 text-white" : "bg-gray-100"}`}>
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

- [ ] **Step 2: Add route in App.tsx**

```tsx
import NotificationsPage from "./pages/NotificationsPage";
// ...
<Route path="/notifications" element={<ForcedPasswordGate><NotificationsPage /></ForcedPasswordGate>} />
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/NotificationsPage.tsx frontend/src/App.tsx
git commit -m "feat: add NotificationsPage with routing"
```

---

### Task 10: ProfilePage — Telegram, preferences, scopes

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx`

Add three new sections to ProfilePage, after the existing field updates section:

- [ ] **Step 1: Add Telegram link section**

```tsx
import { useState, useEffect } from "react";
import { generateTelegramCode, getTelegramStatus, unlinkTelegram, TelegramStatus } from "../api/telegram";
import { getPreferences, updatePreferences, listCommanderScopes, addCommanderScope, removeCommanderScope, NotificationPref, CommanderScope } from "../api/notifications";

// Inside ProfilePage component, after fieldUpdates state:
const [tgStatus, setTgStatus] = useState<TelegramStatus | null>(null);
const [tgCode, setTgCode] = useState<string | null>(null);
const [tgPolling, setTgPolling] = useState(false);
const [prefs, setPrefs] = useState<NotificationPref[]>([]);
const [scopes, setScopes] = useState<CommanderScope[]>([]);

useEffect(() => {
  getTelegramStatus().then(setTgStatus).catch(() => {});
  getPreferences().then(setPrefs).catch(() => {});
  if (user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin") {
    listCommanderScopes().then(setScopes).catch(() => {});
  }
}, [user]);

useEffect(() => {
  if (!tgPolling) return;
  const interval = setInterval(async () => {
    try {
      const s = await getTelegramStatus();
      setTgStatus(s);
      if (s?.is_verified) {
        setTgPolling(false);
        setTgCode(null);
      }
    } catch { setTgPolling(false); }
  }, 3000);
  return () => clearInterval(interval);
}, [tgPolling]);

async function handleLinkTelegram() {
  try {
    const { code } = await generateTelegramCode();
    setTgCode(code);
    setTgPolling(true);
  } catch { /* ignore */ }
}

async function handleUnlinkTelegram() {
  await unlinkTelegram();
  setTgStatus({ is_verified: false });
}

async function handleTogglePref(nt: string, field: "in_app_enabled" | "push_enabled") {
  const updated = prefs.map((p) => p.notification_type === nt ? { ...p, [field]: !p[field] } : p);
  setPrefs(updated);
  await updatePreferences(updated.map((p) => ({ notification_type: p.notification_type, in_app_enabled: p.in_app_enabled, push_enabled: p.push_enabled })));
}

async function handleAddScope() {
  const nodeId = prompt(t("notifications.enter_node_id"));
  if (!nodeId) return;
  try {
    const scope = await addCommanderScope(nodeId);
    setScopes((prev) => [...prev, scope]);
  } catch { alert(t("notifications.scope_add_error")); }
}

async function handleRemoveScope(id: string) {
  await removeCommanderScope(id);
  setScopes((prev) => prev.filter((s) => s.id !== id));
}
```

Then render the three sections in the JSX after the existing sections:

```tsx
{/* Telegram link section */}
<section className="bg-white rounded-lg shadow p-6 mt-4 space-y-3">
  <h3 className="text-lg font-semibold">{t("notifications.telegram")}</h3>
  {tgCode ? (
    <div>
      <p className="text-sm">{t("notifications.send_code_to_bot")}</p>
      <div className="flex items-center gap-2 mt-2">
        <code className="bg-gray-100 px-3 py-1 rounded text-lg font-mono">{tgCode}</code>
        <button onClick={() => navigator.clipboard.writeText(tgCode)} className="text-xs text-indigo-600 hover:text-indigo-800">
          {t("notifications.copy")}
        </button>
      </div>
      {tgPolling && <p className="text-xs text-gray-500 mt-1">{t("notifications.waiting_for_verification")}</p>}
    </div>
  ) : tgStatus?.is_verified ? (
    <div>
      <p className="text-sm">✅ {t("notifications.linked_to")} @{tgStatus.telegram_username || "?"}</p>
      <button onClick={handleUnlinkTelegram} className="text-sm text-red-600 hover:text-red-800 mt-2">
        {t("notifications.unlink")}
      </button>
    </div>
  ) : (
    <button onClick={handleLinkTelegram} className="bg-indigo-600 text-white px-4 py-2 rounded text-sm hover:bg-indigo-700">
      {t("notifications.link_telegram")}
    </button>
  )}
</section>

{/* Notification preferences section */}
<section className="bg-white rounded-lg shadow p-6 mt-4 space-y-3">
  <h3 className="text-lg font-semibold">{t("notifications.preferences")}</h3>
  <div className="space-y-2">
    {prefs.map((p) => (
      <div key={p.notification_type} className="flex items-center justify-between py-1 border-b text-sm">
        <span>{t(`notifications.type_${p.notification_type}`)}</span>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={p.in_app_enabled} onChange={() => handleTogglePref(p.notification_type, "in_app_enabled")} />
            <span className="text-xs">{t("notifications.in_app")}</span>
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={p.push_enabled} onChange={() => handleTogglePref(p.notification_type, "push_enabled")} />
            <span className="text-xs">{t("notifications.push")}</span>
          </label>
        </div>
      </div>
    ))}
  </div>
</section>

{/* Commander scopes section */}
{(user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin") && (
  <section className="bg-white rounded-lg shadow p-6 mt-4 space-y-3">
    <h3 className="text-lg font-semibold">{t("notifications.commander_scopes")}</h3>
    <p className="text-xs text-gray-500">{t("notifications.commander_scopes_hint")}</p>
    {scopes.length === 0 ? (
      <p className="text-sm text-gray-500">{t("notifications.no_scopes")}</p>
    ) : (
      <ul className="space-y-1">
        {scopes.map((s) => (
          <li key={s.id} className="flex items-center justify-between text-sm py-1 border-b">
            <span>{s.hierarchy_node_id}</span>
            <button onClick={() => handleRemoveScope(s.id)} className="text-red-500 hover:text-red-700 text-xs">
              {t("notifications.remove")}
            </button>
          </li>
        ))}
      </ul>
    )}
    <button onClick={handleAddScope} className="text-sm text-indigo-600 hover:text-indigo-800">
      + {t("notifications.add_scope")}
    </button>
  </section>
)}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/ProfilePage.tsx
git commit -m "feat: add telegram link, notification prefs, and commander scopes to profile"
```

---

### Task 11: i18n strings

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add notification-related translations**

Add under the `notifications` key in `he.json`:

```json
"notifications": {
  "title": "התראות",
  "all": "הכל",
  "unread": "לא נקרא",
  "none": "אין התראות",
  "mark_read": "סמן כנקרא",
  "mark_all_read": "סמן הכל כנקרא",
  "dismiss": "מחק",
  "view_all": "לכל ההתראות",
  "telegram": "טלגרם",
  "link_telegram": "קשר חשבון טלגרם",
  "send_code_to_bot": "שלח קוד זה לבוט:",
  "copy": "העתק",
  "waiting_for_verification": "ממתין לאימות...",
  "linked_to": "מחובר ל-",
  "unlink": "נתק",
  "preferences": "העדפות התראות",
  "in_app": "באפליקציה",
  "push": "בטלגרם",
  "commander_scopes": "התראות מפקדים",
  "commander_scopes_hint": "בחר אילו יחידות תחת פיקודך תקבל עליהן התראות",
  "no_scopes": "לא נבחרו תחומים",
  "add_scope": "הוסף תחום",
  "remove": "הסר",
  "enter_node_id": "הכנס מזהה צומת בהיררכיה",
  "scope_add_error": "שגיאה בהוספת התחום",
  "type_swap_offer": "הצעת החלפה",
  "type_swap_accepted": "החלפה אושרה",
  "type_swap_rejected": "החלפה נדחתה",
  "type_exemption_approved": "פטור אושר",
  "type_exemption_rejected": "פטור נדחה",
  "type_constraint_approved": "אילוץ אושר",
  "type_constraint_rejected": "אילוץ נדחה",
  "type_assignment_created": "תורנות חדשה",
  "type_assignment_removed": "תורנות בוטלה",
  "type_score_adjusted": "ניקוד עודכן",
  "type_announcement": "הודעה"
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "feat: add notification i18n strings"
```

---

### Task 12: Wire notifications into existing services

**Files:**
- Modify: `backend/app/services/swaps.py`
- Modify: `backend/app/services/exemption_requests.py`
- Modify: `backend/app/services/constraints.py` (if approval exists)
- Modify: `backend/app/services/assignments.py`

- [ ] **Step 1: Add notification calls to swaps service**

In `backend/app/services/swaps.py`:

In `claim_request`, after the swap is claimed → create `swap_offer` notification for the target if target_soldier_id is set, or for all potential covering soldiers.

In `approve_side`, when both sides approved and `_apply_cover` is called → create `swap_accepted` notification for both parties.

In `reject_request` → create `swap_rejected` notification for requester.

```python
from app.services.notifications import create_notification
from app.db.models import NotificationType

# Example — in approve_side after both sides approved:
if req.requester_side_approved and req.covering_side_approved:
    create_notification(session, soldier_id=req.requesting_soldier_id,
                        type=NotificationType.swap_accepted,
                        title="בקשת ההחלפה אושרה",
                        reference_type="swap_request", reference_id=req.id,
                        actor_id=actor_id)
    if req.covering_soldier_id:
        create_notification(session, soldier_id=req.covering_soldier_id,
                            type=NotificationType.swap_accepted,
                            title="בקשת ההחלפה אושרה",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
```

Similar patterns in other service files.

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/
git commit -m "feat: wire notifications into swap, exemption, constraint, and assignment services"
```

---

### Task 13: End-to-end verification

- [ ] **Step 1: Run backend tests**

```bash
cd backend && python -m pytest tests/integration/test_notifications_api.py -v
```

- [ ] **Step 2: Run frontend type check + build**

```bash
cd frontend && npx tsc --noEmit && npx vite build
```

- [ ] **Step 3: Run full test suite (if time allows)**

```bash
cd backend && python -m pytest
```

---

### Task 14: Docker Compose — add bot service

- [ ] **Step 1: Add bot container to docker-compose.yml**

```yaml
services:
  # ... existing services ...

  telegram-bot:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: python -m bot.main
    env_file:
      - .env
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_BOT_USERNAME=${TELEGRAM_BOT_USERNAME}
      - DATABASE_URL=${DATABASE_URL}
    depends_on:
      - db
    restart: unless-stopped
```

- [ ] **Step 2: Update .env.example with new vars**

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "chore: add telegram-bot service to docker-compose"
```
