"""First-boot script: create initial admin + system holding node. Idempotent."""
from __future__ import annotations

import sys
import uuid

from sqlalchemy import select

from app.auth.password import hash_password
from app.db.models import HierarchyNode, Soldier, SystemSetting
from app.db.session import session_scope
from app.settings import get_settings


def _ensure_admin(session, settings) -> None:
    pn = settings.bootstrap_admin_personal_number
    fn = settings.bootstrap_admin_full_name
    pw = settings.bootstrap_admin_password
    if not (pn and fn and pw):
        print("bootstrap: BOOTSTRAP_ADMIN_* env vars not all set; skipping admin.")
        return
    existing = session.execute(
        select(Soldier).where(Soldier.role == "admin").limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        print("bootstrap: an admin already exists; skipping.")
        return
    admin = Soldier(
        personal_number=pn,
        full_name=fn,
        password_hash=hash_password(pw),
        role="admin",
        must_change_password=False,
    )
    session.add(admin)
    session.flush()
    print(f"bootstrap: created admin id={admin.id} personal_number={pn}")


def _ensure_root_node(session) -> None:
    if session.get(SystemSetting, "system.root_node_id") is not None:
        print("bootstrap: root node already exists; skipping.")
        return
    node = HierarchyNode(
        level="corps",
        name="כלל המסגרת",
        parent_id=None,
        commander_id=None,
        path_ids=[],
    )
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    session.flush()
    session.add(SystemSetting(key="system.root_node_id", value=str(node.id), updated_by=None))
    print(f"bootstrap: created root node id={node.id}")


def _ensure_holding_node(session) -> None:
    if session.get(SystemSetting, "system.holding_node_id") is not None:
        print("bootstrap: holding node already exists; skipping.")
        return
    root_setting = session.get(SystemSetting, "system.root_node_id")
    root = session.get(HierarchyNode, uuid.UUID(root_setting.value)) if root_setting else None
    node = HierarchyNode(
        level="division",
        name="מסגרת ממתינים לקליטה",
        parent_id=root.id if root else None,
        commander_id=None,
        path_ids=[],
    )
    session.add(node)
    session.flush()
    node.path_ids = [*(root.path_ids if root else []), node.id]
    session.flush()
    session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    print(f"bootstrap: created holding node id={node.id}")


def main() -> int:
    settings = get_settings()
    with session_scope() as session:
        _ensure_admin(session, settings)
        _ensure_root_node(session)
        _ensure_holding_node(session)
        session.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
