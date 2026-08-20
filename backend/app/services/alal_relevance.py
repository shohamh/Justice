from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import node_in_scope
from app.db.models import (
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    RangeType,
    Soldier,
    SoldierExemption,
)

# How far out an exemption must still run before we stop notifying the soldier
# about it -- an exemption ending sooner than this still warrants the warning,
# since they'll need a current qualification again shortly after it lapses.
_SUPPRESSION_MIN_REMAINING_DAYS = 90


def active_alal_duty_types(session: Session) -> list[DutyType]:
    """All active DutyTypes requiring an אל"ל range qualification, regardless of
    hierarchy scope. Callers checking many soldiers in one pass (e.g. a daily
    worker scanning the whole roster) should fetch this once and pass it to
    `is_alal_relevant` via `active_alal_duty_types=`, instead of letting each
    call re-run this query."""
    return session.execute(
        select(DutyType).where(
            DutyType.required_range_type == RangeType.alal, DutyType.active.is_(True),
        )
    ).scalars().all()


def _alal_duty_types(
    session: Session, *, node: HierarchyNode, all_active: list[DutyType] | None = None,
) -> list[DutyType]:
    duty_types = all_active if all_active is not None else active_alal_duty_types(session)
    return [
        duty_type for duty_type in duty_types
        if node_in_scope(duty_type.eligible_node_ids, node.path_ids)
    ]


def _is_suppressed_by_exemption(
    session: Session, *, soldier: Soldier, alal_duty_types: list[DutyType], as_of: date,
) -> bool:
    """True iff every alal-requiring duty type in `alal_duty_types` is covered by
    an active, non-revoked exemption that won't lapse within the next
    `_SUPPRESSION_MIN_REMAINING_DAYS` days (or is permanent)."""
    min_end_date = as_of + timedelta(days=_SUPPRESSION_MIN_REMAINING_DAYS)
    long_enough_exemptions = [
        (exemption, exemption_type)
        for exemption, exemption_type in session.execute(
            select(SoldierExemption, ExemptionType)
            .join(ExemptionType, SoldierExemption.exemption_type_id == ExemptionType.id)
            .where(
                SoldierExemption.soldier_id == soldier.id,
                SoldierExemption.revoked_at.is_(None),
                SoldierExemption.start_date <= as_of,
            )
        ).all()
        if exemption.end_date is None or exemption.end_date >= min_end_date
    ]
    if not long_enough_exemptions:
        return False
    if any(
        exemption_type.is_global or exemption_type.forbids_weapons
        for _exemption, exemption_type in long_enough_exemptions
    ):
        return True

    covered_duty_type_ids = set(
        session.execute(
            select(ExemptionDutyTypeMap.duty_type_id).where(
                ExemptionDutyTypeMap.exemption_type_id.in_(
                    [exemption_type.id for _exemption, exemption_type in long_enough_exemptions]
                )
            )
        ).scalars()
    )
    return all(duty_type.id in covered_duty_type_ids for duty_type in alal_duty_types)


def is_alal_relevant(
    session: Session, soldier: Soldier, *, active_alal_duty_types: list[DutyType] | None = None,
) -> bool:
    """True iff soldier's hierarchy node is structurally in scope for any active
    DutyType requiring required_range_type == alal, AND the soldier isn't
    exempt from all of them for the foreseeable future (see
    _is_suppressed_by_exemption).

    Runs its query directly on every call rather than caching: caching this
    per-process was unsafe under the multi-worker prod deploy (each uvicorn
    worker has its own process memory, so invalidating the cache from one
    worker's write path left other workers serving a stale value indefinitely).
    The underlying queries are cheap and scoped to the soldier's single
    hierarchy node, and /me already performs several queries per request, so
    querying fresh here costs little.

    `active_alal_duty_types` is an optional escape hatch for callers checking
    many soldiers in one pass (e.g. a daily worker scanning the whole roster):
    pass the result of `active_alal_duty_types(session)` fetched once up front
    to skip re-running that query for every soldier. Single-soldier callers
    (like /me) should omit it.
    """
    if soldier.hierarchy_node_id is None:
        return False
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None:
        return False
    alal_duty_types = _alal_duty_types(session, node=node, all_active=active_alal_duty_types)
    if not alal_duty_types:
        return False
    return not _is_suppressed_by_exemption(
        session, soldier=soldier, alal_duty_types=alal_duty_types, as_of=date.today(),
    )
