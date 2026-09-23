from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HrHierarchyNodeMap
from app.services.hr.schemas import HrUser
from app.services.settings_loader import SettingNotFound, get_setting

# Priority order for which org-unit id determines a person's placement.
# TODO: placeholder order, unconfirmed against real HR data — see design
# doc's "Open questions" section.
_PLACEMENT_ID_PRIORITY = ("team_id", "mador_id", "branch_id", "department_id", "shetach_id", "unit_id")


def _holding_node_id(session: Session) -> uuid.UUID:
    try:
        return uuid.UUID(get_setting(session, "system.holding_node_id"))
    except SettingNotFound as exc:
        raise RuntimeError("system.holding_node_id is not bootstrapped") from exc


def resolve_placement_node_id(session: Session, user: HrUser) -> uuid.UUID:
    for field_name in _PLACEMENT_ID_PRIORITY:
        group_id = getattr(user, field_name)
        if group_id is None:
            continue
        mapping = session.execute(
            select(HrHierarchyNodeMap).where(HrHierarchyNodeMap.hr_group_id == group_id)
        ).scalar_one_or_none()
        if mapping is not None:
            return mapping.node_id
    return _holding_node_id(session)
