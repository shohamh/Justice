from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import event

from app.db.models import (
    DutyLocation,
    DutyType,
    ExemptionType,
    SoldierExemption,
    SwapCandidate,
    SwapRequest,
)
from app.services import assignments as assignments_svc
from app.services.commander_dashboard import (
    _score_data,
    alerts,
    potential_counts,
    soldiers_in_subtree,
    summary_cards,
    upcoming_duties,
)
from tests.helpers import create_node, create_soldier


def _count_selects(session, fn):
    """Run fn() and return the number of SELECT statements it issues."""
    count = 0

    def _counter(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal count
        if statement.lstrip().upper().startswith("SELECT"):
            count += 1

    event.listen(session.bind, "before_cursor_execute", _counter)
    try:
        result = fn()
    finally:
        event.remove(session.bind, "before_cursor_execute", _counter)
    return result, count


def _capture_selects(session, fn):
    statements = []

    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement.lower())

    event.listen(session.bind, "before_cursor_execute", _capture)
    try:
        result = fn()
    finally:
        event.remove(session.bind, "before_cursor_execute", _capture)
    return result, statements


def test_upcoming_reads_only_soldiers_attached_to_matching_assignments(admin_session):
    node = create_node(admin_session, level="unit", name="upcoming_narrow_read_test")
    create_soldier(admin_session, personal_number="7949001", hierarchy_node_id=node.id)
    admin_session.commit()

    result, statements = _capture_selects(
        admin_session, lambda: upcoming_duties(admin_session, subtree_ids=[node.id], days=7)
    )

    assert result == []
    assert len(statements) == 1
    assert not any("select soldiers." in statement for statement in statements)


def test_alerts_reads_only_score_and_display_soldier_columns(admin_session):
    node = create_node(admin_session, level="unit", name="alerts_narrow_read_test")
    create_soldier(admin_session, personal_number="7949002", hierarchy_node_id=node.id)
    admin_session.commit()

    _, statements = _capture_selects(
        admin_session, lambda: alerts(admin_session, subtree_ids=[node.id])
    )

    soldier_reads = [statement for statement in statements if "from soldiers" in statement]
    assert soldier_reads
    assert all("soldiers.password_hash" not in statement for statement in soldier_reads)


def test_summary_cards_counts_pending_approval_swaps(admin_session):
    node = create_node(admin_session, level="unit", name="pending_swap_test")
    soldier = create_soldier(admin_session, personal_number="7930001", hierarchy_node_id=node.id)
    covering = create_soldier(admin_session, personal_number="7930003")

    baseline = summary_cards(admin_session, subtree_ids=[node.id])

    dt = DutyType(name="dt_pending_swap_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_pending_swap_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    assignment = assignments_svc.create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
    )
    admin_session.flush()
    # Open swap request with one live (accepted) candidate — the current
    # equivalent of the old "pending_approval" status, now that manager
    # approval is tracked per-candidate rather than on the parent request.
    req = SwapRequest(
        duty_assignment_id=assignment.id,
        duty_date=date(2026, 8, 1),
        requesting_soldier_id=soldier.id,
        status="open",
    )
    admin_session.add(req)
    admin_session.flush()
    candidate = SwapCandidate(
        swap_request_id=req.id,
        soldier_id=covering.id,
        source="invited",
        status="accepted",
        soldier_side_approved=True,
    )
    admin_session.add(candidate)
    admin_session.commit()

    cards = summary_cards(admin_session, subtree_ids=[node.id])
    assert cards["approvals_pending"] == baseline["approvals_pending"] + 1


def test_upcoming_duties_includes_algorithm_draft(admin_session):
    from datetime import date as _date

    from app.db.models import DutyAssignment

    node = create_node(admin_session, level="unit", name="upcoming_draft_test")
    soldier = create_soldier(admin_session, personal_number="7940001", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_upcoming_draft_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_upcoming_draft_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=_date.today(),
            end_date=_date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    days = upcoming_duties(admin_session, subtree_ids=[node.id], days=7)
    all_assignments = [a for day in days for a in day["assignments"]]
    assert len(all_assignments) == 1
    assert all_assignments[0]["status"] == "algorithm_draft"


def test_upcoming_duties_with_no_horizon_includes_far_future_assignment(admin_session):
    from datetime import date as _date

    from app.db.models import DutyAssignment

    node = create_node(admin_session, level="unit", name="upcoming_far_future_test")
    soldier = create_soldier(admin_session, personal_number="7940002", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_upcoming_far_future_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_upcoming_far_future_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    far_start = _date.today() + timedelta(days=30)
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=far_start,
            end_date=far_start + timedelta(days=1),
            status="published",
        )
    )
    admin_session.commit()

    days_capped = upcoming_duties(admin_session, subtree_ids=[node.id], days=7)
    assert [a for day in days_capped for a in day["assignments"]] == []

    days_uncapped = upcoming_duties(admin_session, subtree_ids=[node.id], days=None)
    all_assignments = [a for day in days_uncapped for a in day["assignments"]]
    assert len(all_assignments) == 1
    assert all_assignments[0]["start_date"] == str(far_start)
    # Only days with assignments are present — no empty-day filler.
    assert all(day["assignments"] for day in days_uncapped)


def test_summary_cards_upcoming_count_includes_algorithm_draft(admin_session):
    from datetime import date as _date

    from app.db.models import DutyAssignment

    node = create_node(admin_session, level="unit", name="summary_draft_test")
    soldier = create_soldier(admin_session, personal_number="7940002", hierarchy_node_id=node.id)
    baseline = summary_cards(admin_session, subtree_ids=[node.id])

    dt = DutyType(name="dt_summary_draft_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_summary_draft_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=_date.today(),
            end_date=_date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    cards = summary_cards(admin_session, subtree_ids=[node.id])
    assert cards["upcoming_duties_7d"] == baseline["upcoming_duties_7d"] + 1


def _grant_exemption(session, soldier_id, *, is_global=False, end_date=None):
    et = ExemptionType(name=f"cd-exempt-{soldier_id}-{is_global}", is_global=is_global)
    session.add(et)
    session.flush()
    se = SoldierExemption(
        soldier_id=soldier_id,
        exemption_type_id=et.id,
        start_date=date(2020, 1, 1),
        end_date=end_date,
    )
    session.add(se)
    session.flush()
    return se


def test_soldiers_in_subtree_query_count_does_not_scale_with_soldier_count(admin_session):
    node = create_node(admin_session, level="unit", name="soldiers_subtree_query_count_test")
    soldiers = [
        create_soldier(admin_session, personal_number=f"7950{i:03d}", hierarchy_node_id=node.id)
        for i in range(8)
    ]
    # Half the soldiers get a global exemption, so the batched query still
    # has to distinguish "has an active global exemption" per soldier.
    for s in soldiers[:4]:
        _grant_exemption(admin_session, s.id, is_global=True)
    admin_session.commit()

    _, select_count = _count_selects(
        admin_session, lambda: soldiers_in_subtree(admin_session, subtree_ids=[node.id])
    )

    # Fixed-cost regardless of subtree size: this must NOT scale with the
    # number of soldiers (was 1 SoldierExemption query + up to 1
    # ExemptionType lookup per soldier before batching).
    assert select_count <= 5


def test_soldiers_in_subtree_marks_active_global_exemption_as_exempt(admin_session):
    node = create_node(admin_session, level="unit", name="soldiers_subtree_exempt_status_test")
    exempt_soldier = create_soldier(
        admin_session, personal_number="7951001", hierarchy_node_id=node.id
    )
    plain_soldier = create_soldier(
        admin_session, personal_number="7951002", hierarchy_node_id=node.id
    )
    _grant_exemption(admin_session, exempt_soldier.id, is_global=True)
    admin_session.commit()

    result = {r["id"]: r for r in soldiers_in_subtree(admin_session, subtree_ids=[node.id])}

    assert result[exempt_soldier.id]["status"] == "exempt"
    assert result[plain_soldier.id]["status"] == "active"


def test_alerts_query_count_does_not_scale_with_soldier_count(admin_session):
    node = create_node(admin_session, level="unit", name="alerts_query_count_test")
    soldiers = [
        create_soldier(admin_session, personal_number=f"7952{i:03d}", hierarchy_node_id=node.id)
        for i in range(8)
    ]
    today = date.today()
    for s in soldiers[:4]:
        _grant_exemption(admin_session, s.id, end_date=today + timedelta(days=3))
    admin_session.commit()

    _, select_count = _count_selects(
        admin_session, lambda: alerts(admin_session, subtree_ids=[node.id])
    )

    assert select_count <= 6


def test_alerts_includes_soon_expiring_exemption(admin_session):
    node = create_node(admin_session, level="unit", name="alerts_expiring_exemption_test")
    soldier = create_soldier(admin_session, personal_number="7953001", hierarchy_node_id=node.id)
    today = date.today()
    se = _grant_exemption(admin_session, soldier.id, end_date=today + timedelta(days=3))
    admin_session.commit()

    result = alerts(admin_session, subtree_ids=[node.id])

    matching = [a for a in result if a["soldier_id"] == soldier.id and a["severity"] == "info"]
    assert len(matching) == 1
    assert se.end_date.strftime("%d.%m.%Y") in matching[0]["message"]


def test_alerts_excludes_revoked_exemption(admin_session):
    """A revoked exemption is no longer in effect, so it must not still page the
    commander with a stale "about to expire" alert."""
    node = create_node(admin_session, level="unit", name="alerts_revoked_exemption_test")
    soldier = create_soldier(admin_session, personal_number="7953002", hierarchy_node_id=node.id)
    today = date.today()
    se = _grant_exemption(admin_session, soldier.id, end_date=today + timedelta(days=3))
    se.revoked_at = datetime.now(timezone.utc)
    admin_session.commit()

    result = alerts(admin_session, subtree_ids=[node.id])

    matching = [a for a in result if a["soldier_id"] == soldier.id and a["severity"] == "info"]
    assert matching == []


def test_score_data_aggregates_assignment_history_in_database(admin_session):
    """The all-time score path must not hydrate every historical assignment."""
    node = create_node(admin_session, level="unit", name="score_aggregate_query_test")
    soldier = create_soldier(admin_session, personal_number="7954001", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_score_aggregate_query_test", score_per_day=Decimal("2.50"))
    loc = DutyLocation(name="loc_score_aggregate_query_test")
    admin_session.add_all([dt, loc])
    admin_session.flush()

    from app.db.models import DutyAssignment

    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 4),
            status="published",
        )
    )
    admin_session.commit()

    statements: list[str] = []

    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "duty_assignments" in statement.lower():
            statements.append(statement)

    event.listen(admin_session.bind, "before_cursor_execute", _capture)
    try:
        result = _score_data(admin_session, [soldier])
    finally:
        event.remove(admin_session.bind, "before_cursor_execute", _capture)

    assert result[soldier.id]["cumulative_score"] == Decimal("7.50")
    assert any(
        "sum(" in statement.lower() and "group by" in statement.lower() for statement in statements
    )


def test_summary_cards_batches_expiring_exemption_counts(admin_session):
    node = create_node(admin_session, level="unit", name="summary_expiring_batch_test")
    soldiers = [
        create_soldier(admin_session, personal_number=f"7955{i:03d}", hierarchy_node_id=node.id)
        for i in range(8)
    ]
    today = date.today()
    for soldier in soldiers[:4]:
        _grant_exemption(admin_session, soldier.id, end_date=today + timedelta(days=3))
    admin_session.commit()

    result, select_count = _count_selects(
        admin_session, lambda: summary_cards(admin_session, subtree_ids=[node.id])
    )

    assert result["alerts_count"] == 4
    assert select_count <= 9


def test_summary_cards_batches_shift_assignment_counts(admin_session):
    from app.db.models import DutyAssignment, DutyShift

    node = create_node(admin_session, level="unit", name="summary_shift_batch_test")
    soldier = create_soldier(admin_session, personal_number="7956001", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_summary_shift_batch_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_summary_shift_batch_test")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shifts = [
        DutyShift(
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
            required_count=2,
        )
        for _ in range(8)
    ]
    admin_session.add_all(shifts)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            duty_shift_id=shifts[0].id,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
            status="published",
        )
    )
    admin_session.commit()

    result, select_count = _count_selects(
        admin_session, lambda: summary_cards(admin_session, subtree_ids=[node.id])
    )

    assert result["unfilled_gaps"] == 8
    assert select_count < 20


def test_potential_counts_aggregates_active_soldiers_across_scoped_roots(admin_session):
    first = create_node(admin_session, level="unit", name="potential_counts_first")
    second = create_node(admin_session, level="unit", name="potential_counts_second")
    outside = create_node(admin_session, level="unit", name="potential_counts_outside")
    today = date.today()

    future = create_soldier(admin_session, personal_number="7957001", hierarchy_node_id=first.id)
    future.mandatory_end_date = today + timedelta(days=1)
    future.rank = "sgan_aluf"
    future.bahad1_graduate = True
    future.is_officer = True

    boundary = create_soldier(admin_session, personal_number="7957002", hierarchy_node_id=first.id)
    boundary.mandatory_end_date = today
    boundary.rank = "rav_saren"
    boundary.is_officer = None

    second_root = create_soldier(admin_session, personal_number="7957003", hierarchy_node_id=second.id)
    second_root.mandatory_end_date = None
    second_root.rank = "saren"
    second_root.bahad1_graduate = True
    second_root.is_officer = False

    plain = create_soldier(admin_session, personal_number="7957004", hierarchy_node_id=second.id)
    plain.mandatory_end_date = today - timedelta(days=1)
    plain.rank = "seren"  # Outside the fixed career rank set.
    plain.bahad1_graduate = False
    plain.is_officer = None

    departed = create_soldier(admin_session, personal_number="7957005", hierarchy_node_id=first.id)
    departed.mandatory_end_date = today + timedelta(days=1)
    departed.rank = "saren"
    departed.bahad1_graduate = True
    departed.is_officer = True
    departed.left_at = today

    unscoped = create_soldier(admin_session, personal_number="7957006", hierarchy_node_id=outside.id)
    unscoped.mandatory_end_date = today + timedelta(days=1)
    unscoped.rank = "saren"
    unscoped.bahad1_graduate = True
    unscoped.is_officer = True
    admin_session.commit()

    result, statements = _capture_selects(
        admin_session,
        lambda: potential_counts(admin_session, subtree_ids=[first.id, second.id]),
    )

    assert [item["count"] for item in result] == [1, 3, 2, 1, 4]
    assert all(item["unit_total"] is None for item in result)
    assert len(statements) == 1
    assert "sum(" in statements[0] and "case" in statements[0]


def test_potential_counts_no_scope_has_zero_counts_without_query(admin_session):
    result, statements = _capture_selects(
        admin_session, lambda: potential_counts(admin_session, subtree_ids=[])
    )
    assert [item["count"] for item in result] == [0, 0, 0, 0, 0]
    assert statements == []
