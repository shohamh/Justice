from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import node_in_scope
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


def _has_any_eligible_weapon_duty_type(
    session: Session, *, soldier: Soldier, range_type: str,
) -> bool:
    if soldier.hierarchy_node_id is None:
        return False
    from app.services.range_auto_assign import _qualification_types_at_or_above

    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None:
        return False
    relevant_range_types = _qualification_types_at_or_above(range_type)
    weapon_duty_types = session.execute(
        select(DutyType).where(
            DutyType.requires_weapon.is_(True),
            DutyType.active.is_(True),
            (DutyType.required_range_type.is_(None) | DutyType.required_range_type.in_(relevant_range_types)),
        )
    ).scalars().all()
    for duty_type in weapon_duty_types:
        if node_in_scope(duty_type.eligible_node_ids, node.path_ids):
            return True
    return False


def is_range_exempt(
    session: Session, *, soldier: Soldier, event_date: date, range_type: str,
) -> bool:
    """True iff the soldier is exempt from a range event on event_date, per either:
    (1) an active global or weapons-forbidding exemption covering that date, or
    (2) structural ineligibility for any relevant weapon-requiring duty type."""
    if _has_covering_weapon_exemption(session, soldier_id=soldier.id, event_date=event_date):
        return True
    return not _has_any_eligible_weapon_duty_type(
        session, soldier=soldier, range_type=range_type,
    )
