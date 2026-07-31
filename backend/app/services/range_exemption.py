from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyType, ExemptionType, HierarchyNode, Soldier, SoldierExemption


def _has_covering_weapon_exemption(session: Session, *, soldier_id, event_date: date) -> bool:
    rows = session.execute(
        select(SoldierExemption, ExemptionType)
        .join(ExemptionType, SoldierExemption.exemption_type_id == ExemptionType.id)
        .where(
            SoldierExemption.soldier_id == soldier_id,
            SoldierExemption.revoked_at.is_(None),
            SoldierExemption.start_date <= event_date,
        )
    ).all()
    for exemption, exemption_type in rows:
        if exemption.end_date is not None and exemption.end_date < event_date:
            continue
        if exemption_type.is_global or exemption_type.forbids_weapons:
            return True
    return False


def _has_any_eligible_weapon_duty_type(session: Session, *, soldier: Soldier) -> bool:
    if soldier.hierarchy_node_id is None:
        return False
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None:
        return False
    weapon_duty_types = session.execute(
        select(DutyType).where(DutyType.requires_weapon.is_(True), DutyType.active.is_(True))
    ).scalars().all()
    for duty_type in weapon_duty_types:
        if duty_type.eligible_node_ids and node.id in duty_type.eligible_node_ids:
            return True
    return False


def is_range_exempt(session: Session, *, soldier: Soldier, event_date: date) -> bool:
    """True iff the soldier is exempt from a range event on event_date, per either:
    (1) an active global or weapons-forbidding exemption covering that date, or
    (2) structural ineligibility for any weapon-requiring duty type."""
    if _has_covering_weapon_exemption(session, soldier_id=soldier.id, event_date=event_date):
        return True
    return not _has_any_eligible_weapon_duty_type(session, soldier=soldier)
