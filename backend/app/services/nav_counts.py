"""Count-only navigation badge queries.

This module mirrors the source endpoints consumed by UnifiedNav while keeping
the aggregate request in one database session. It deliberately returns no
pending request, soldier, or approval DTOs.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.authz import Action, can, is_commander, is_duty_manager, scope_root_ids
from app.db.models import (
    ForcedCallup,
    HierarchyLevelType,
    HierarchyNode,
    PersonalConstraint,
    Soldier,
    SoldierEnrollmentRequest,
    SoldierFieldUpdate,
    SwapCandidate,
    SwapManagerApproval,
    SwapRequest,
)
from app.services import constraints, exemption_requests, hierarchy_transfers, swaps
from app.services.approval_scope import (
    commander_chain_for_soldier,
    duty_manager_chain_for_soldier,
    exemption_approval_flags,
)
from app.services.authority import rank_advancement_edit_authorized
from app.services.settings_loader import SettingNotFound, get_setting

logger = logging.getLogger(__name__)


def _safe_count(session: Session, source: str, count: Callable[[], int]) -> int:
    """Keep one failed count source from discarding the other navigation badges."""
    try:
        # A failed statement aborts a PostgreSQL transaction until it is rolled
        # back. Isolate each source with a savepoint while retaining one request
        # session and the existing per-source zero-on-error behavior.
        with session.begin_nested():
            return int(count())
    except Exception:
        logger.exception("Navigation badge count source %s failed", source)
        return 0


def _can_approve_constraint(
    session: Session,
    user: Soldier,
    target_soldier_id: uuid.UUID,
    target_node: HierarchyNode | None,
    constraint_status: str,
) -> bool:
    if user.id == target_soldier_id:
        return False
    if user.role == "admin":
        return True
    if constraint_status == "pending_duty_manager" and user.role not in ("duty_manager", "admin"):
        return False
    if constraint_status in ("pending", "pending_commander"):
        from app.services.authority import senior_commander_approval_authorized

        return senior_commander_approval_authorized(session, user=user, target_node=target_node)
    roots = scope_root_ids(session, user)
    return can(
        user,
        Action.CONSTRAINT_APPROVE,
        target_node=target_node,
        roots=roots,
        is_commander=is_commander(session, user.id),
        is_duty_manager=is_duty_manager(session, user.id),
    )


def _count_constraints(session: Session, user: Soldier) -> int:
    roots = scope_root_ids(session, user)
    if user.role != "admin" and not roots:
        # The existing count route rejects an unscoped actor; UnifiedNav catches
        # that source independently and displays zero.
        return 0
    rows = (
        list(session.execute(
            select(PersonalConstraint).where(
                PersonalConstraint.status.in_(("pending_commander", "pending_duty_manager"))
            )
        ).scalars().all())
        if user.role == "admin"
        else constraints.list_pending_approvals(session, node_ids=roots)
    )
    if not rows:
        return 0
    soldier_ids = {row.soldier_id for row in rows}
    soldiers = {
        soldier.id: soldier
        for soldier in session.execute(select(Soldier).where(Soldier.id.in_(soldier_ids))).scalars().all()
    }
    node_ids = {soldier.hierarchy_node_id for soldier in soldiers.values() if soldier.hierarchy_node_id}
    nodes = {
        node.id: node
        for node in session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))).scalars().all()
    } if node_ids else {}
    return sum(
        _can_approve_constraint(
            session,
            user,
            row.soldier_id,
            nodes.get(soldiers[row.soldier_id].hierarchy_node_id)
            if row.soldier_id in soldiers and soldiers[row.soldier_id].hierarchy_node_id
            else None,
            row.status,
        )
        for row in rows
    )


def _can_see_enrollment_exemptions(session: Session, user: Soldier) -> bool:
    from app.auth.authz import dm_scope_node_ids

    try:
        minimum_rank = int(get_setting(session, "enrollment.min_dm_level_rank"))
    except SettingNotFound:
        minimum_rank = 0
    maximum_rank = 0
    for node_id in dm_scope_node_ids(session, user.id):
        node = session.get(HierarchyNode, node_id)
        if node is None:
            continue
        level = session.execute(
            select(HierarchyLevelType).where(HierarchyLevelType.key == node.level)
        ).scalar_one_or_none()
        if level and level.rank > maximum_rank:
            maximum_rank = level.rank
    return user.role == "admin" or maximum_rank >= minimum_rank


def _count_exemptions(session: Session, user: Soldier) -> int:
    roots = scope_root_ids(session, user)
    if not roots:
        return 0
    can_see_enrollment_exemptions = _can_see_enrollment_exemptions(session, user)
    scoped_nodes = select(HierarchyNode.id).where(HierarchyNode.path_ids.overlap(list(roots))).subquery()
    enrolled_soldier_ids = set(session.execute(
        select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(scoped_nodes.c.id)))
    ).scalars().all())
    pending_enrollment_soldier_ids = set(session.execute(
        select(SoldierEnrollmentRequest.soldier_id).where(
            SoldierEnrollmentRequest.status == "pending",
            SoldierEnrollmentRequest.requested_node_id.in_(select(scoped_nodes.c.id)),
        )
    ).scalars().all())
    requests = exemption_requests.list_pending_requests(
        session, list(enrolled_soldier_ids | pending_enrollment_soldier_ids)
    )
    if not requests:
        return 0
    target_ids = {request.soldier_id for request in requests}
    soldiers = {
        soldier.id: soldier
        for soldier in session.execute(select(Soldier).where(Soldier.id.in_(target_ids))).scalars().all()
    }
    node_ids = {soldier.hierarchy_node_id for soldier in soldiers.values() if soldier.hierarchy_node_id}
    nodes = {
        node.id: node
        for node in session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))).scalars().all()
    } if node_ids else {}
    count = 0
    for request in requests:
        if request.enrollment_request_id and not can_see_enrollment_exemptions:
            continue
        soldier = soldiers.get(request.soldier_id)
        node = nodes.get(soldier.hierarchy_node_id) if soldier and soldier.hierarchy_node_id else None
        can_commander_step, can_dm_step = exemption_approval_flags(session, user, node)
        if (request.status == "pending_commander" and can_commander_step) or (
            request.status == "pending_duty_manager" and can_dm_step
        ):
            count += 1
    return count


def _field_update_can_approve(
    session: Session,
    *,
    user: Soldier,
    roots: set[uuid.UUID],
    is_cmd: bool,
    is_dm: bool,
    node: HierarchyNode | None,
    field_name: str,
    status: str,
) -> bool:
    if field_name == "unit_join_date":
        if status not in {"pending_commander", "pending_duty_manager"}:
            return False
        from app.services.approval_scope import unit_join_date_stage_authorized

        stage = "commander" if status == "pending_commander" else "duty_manager"
        return unit_join_date_stage_authorized(session, actor=user, target_node=node, stage=stage)
    if field_name in {"rank", "rank_track", "is_officer", "next_rank_date"}:
        return rank_advancement_edit_authorized(session, user=user, target_node=node)
    decision = Action.MILITARY_LICENSE_DECIDE if field_name == "military_driving_license" else Action.SOLDIER_UPDATE
    return can(user, decision, target_node=node, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def _count_field_updates(session: Session, user: Soldier) -> int:
    pending_statuses = ("pending", "pending_commander", "pending_duty_manager")
    if user.role == "admin":
        return int(session.execute(
            select(func.count()).select_from(SoldierFieldUpdate).where(SoldierFieldUpdate.status.in_(pending_statuses))
        ).scalar_one())
    roots = scope_root_ids(session, user)
    if not roots:
        return 0
    pending = session.execute(
        select(SoldierFieldUpdate).where(SoldierFieldUpdate.status.in_(pending_statuses))
    ).scalars().all()
    if not pending:
        return 0
    soldier_ids = {update.soldier_id for update in pending}
    soldiers = {
        soldier.id: soldier
        for soldier in session.execute(select(Soldier).where(Soldier.id.in_(soldier_ids))).scalars().all()
    }
    node_ids = {soldier.hierarchy_node_id for soldier in soldiers.values() if soldier.hierarchy_node_id}
    nodes = {
        node.id: node
        for node in session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))).scalars().all()
    } if node_ids else {}
    is_cmd = is_commander(session, user.id)
    is_dm = is_duty_manager(session, user.id)
    return sum(
        1
        for update in pending
        if (soldier := soldiers.get(update.soldier_id)) is not None
        and _field_update_can_approve(
            session,
            user=user,
            roots=roots,
            is_cmd=is_cmd,
            is_dm=is_dm,
            node=nodes.get(soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None,
            field_name=update.field_name,
            status=update.status,
        )
    )


def _count_enrollments(session: Session, user: Soldier) -> int:
    if user.role == "admin":
        return int(session.execute(
            select(func.count()).select_from(SoldierEnrollmentRequest).where(
                SoldierEnrollmentRequest.status == "pending"
            )
        ).scalar_one())
    roots = scope_root_ids(session, user)
    if not roots:
        return 0
    return int(session.execute(
        select(func.count())
        .select_from(SoldierEnrollmentRequest)
        .join(HierarchyNode, HierarchyNode.id == SoldierEnrollmentRequest.requested_node_id)
        .where(
            SoldierEnrollmentRequest.status == "pending",
            HierarchyNode.path_ids.overlap(list(roots)),
        )
    ).scalar_one())


def _swap_manager_approver_ids(session: Session, soldier_id: uuid.UUID) -> set[uuid.UUID]:
    approver_ids = set(commander_chain_for_soldier(session, soldier_id))
    try:
        include_duty_managers = bool(get_setting(session, "swaps.require_duty_manager_approval"))
    except SettingNotFound:
        include_duty_managers = True
    if include_duty_managers:
        approver_ids.update(duty_manager_chain_for_soldier(session, soldier_id))
    return approver_ids


def _count_actionable_swaps(session: Session, user: Soldier) -> int:
    if user.role not in ("admin", "duty_manager", "commander"):
        return 0
    pending = swaps.list_pending_approval(session)
    if not pending:
        return 0
    if user.role == "admin":
        # UnifiedNav's existing helper treats every row returned by the admin
        # pending endpoint as actionable.
        return len(pending)

    roots = scope_root_ids(session, user)
    is_cmd = is_commander(session, user.id)
    is_dm = is_duty_manager(session, user.id)
    request_ids = {request.id for request in pending}
    candidates = session.execute(
        select(SwapCandidate).where(SwapCandidate.swap_request_id.in_(request_ids))
    ).scalars().all()
    candidates_by_request: dict[uuid.UUID, list[SwapCandidate]] = {}
    for candidate in candidates:
        candidates_by_request.setdefault(candidate.swap_request_id, []).append(candidate)
    side_soldier_ids = {request.requesting_soldier_id for request in pending}
    side_soldier_ids.update(candidate.soldier_id for candidate in candidates)
    soldiers = {
        soldier.id: soldier
        for soldier in session.execute(select(Soldier).where(Soldier.id.in_(side_soldier_ids))).scalars().all()
    }
    node_ids = {soldier.hierarchy_node_id for soldier in soldiers.values() if soldier.hierarchy_node_id}
    nodes = {
        node.id: node
        for node in session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))).scalars().all()
    } if node_ids else {}
    actor_id = user.id
    overrides = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id.in_(request_ids),
            SwapManagerApproval.commander_id == actor_id,
            or_(SwapManagerApproval.approved.is_(True), SwapManagerApproval.rejected.is_(True)),
        )
    ).scalars().all()
    decided_override_sides = {
        (row.swap_request_id, row.swap_candidate_id, row.side)
        for row in overrides
    }
    chain_membership: dict[uuid.UUID, bool] = {}

    def actor_in_chain(soldier_id: uuid.UUID) -> bool:
        if soldier_id not in chain_membership:
            chain_membership[soldier_id] = actor_id in _swap_manager_approver_ids(session, soldier_id)
        return chain_membership[soldier_id]

    count = 0
    for request in pending:
        requester = soldiers.get(request.requesting_soldier_id)
        requester_node = nodes.get(requester.hierarchy_node_id) if requester and requester.hierarchy_node_id else None
        request_candidates = candidates_by_request.get(request.id, [])
        visible = can(
            user,
            Action.SWAP_APPROVE,
            target_node=requester_node,
            roots=roots,
            is_commander=is_cmd,
            is_duty_manager=is_dm,
        )
        if not visible:
            for candidate in request_candidates:
                target = soldiers.get(candidate.soldier_id)
                target_node = nodes.get(target.hierarchy_node_id) if target and target.hierarchy_node_id else None
                if can(
                    user,
                    Action.SWAP_APPROVE,
                    target_node=target_node,
                    roots=roots,
                    is_commander=is_cmd,
                    is_duty_manager=is_dm,
                ):
                    visible = True
                    break
        if not visible:
            continue

        requester_actionable = actor_in_chain(request.requesting_soldier_id) or (
            request.id, None, "requester"
        ) in decided_override_sides
        candidate_actionable = any(
            candidate.status in ("pending", "accepted")
            and (
                actor_in_chain(candidate.soldier_id)
                or (request.id, candidate.id, "covering") in decided_override_sides
            )
            for candidate in request_candidates
        )
        if requester_actionable or candidate_actionable:
            count += 1
    return count


def _count_hakpaza(session: Session, user: Soldier) -> int:
    try:
        enabled = bool(get_setting(session, "forced_callup.enabled"))
    except SettingNotFound:
        enabled = False
    if not enabled or (user.role != "admin" and not is_duty_manager(session, user.id)):
        return 0
    return int(session.execute(
        select(func.count()).select_from(ForcedCallup).where(ForcedCallup.status == "pending")
    ).scalar_one())


def _count_incoming_swaps(session: Session, user: Soldier) -> int:
    return int(session.execute(
        select(func.count())
        .select_from(SwapRequest)
        .join(SwapCandidate, SwapCandidate.swap_request_id == SwapRequest.id)
        .where(
            SwapCandidate.soldier_id == user.id,
            SwapCandidate.source == "invited",
            SwapCandidate.status == "pending",
            SwapRequest.status == "open",
        )
    ).scalar_one())


def get_nav_counts(session: Session, user: Soldier) -> dict[str, int]:
    """Return the exact count fields consumed by UnifiedNav in one session."""
    can_approve = user.role == "admin" or is_commander(session, user.id) or is_duty_manager(session, user.id)
    approval_sources: tuple[tuple[str, Callable[[], int]], ...] = (
        ("constraints", lambda: _count_constraints(session, user)),
        ("exemptions", lambda: _count_exemptions(session, user)),
        ("field_updates", lambda: _count_field_updates(session, user)),
        ("enrollments", lambda: _count_enrollments(session, user)),
        ("swaps", lambda: _count_actionable_swaps(session, user)),
        (
            "transfers",
            lambda: len(hierarchy_transfers.list_pending_for_approver(session, approver_id=user.id)),
        ),
    )
    approvals = sum(
        _safe_count(session, source, count)
        for source, count in approval_sources
    ) if can_approve else 0
    return {
        "approvals": approvals,
        "hakpaza": _safe_count(session, "hakpaza", lambda: _count_hakpaza(session, user)),
        "incoming_swaps": _safe_count(
            session, "incoming_swaps", lambda: _count_incoming_swaps(session, user)
        ),
    }
