from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation
from app.services.duty_config import create_duty_type
from app.services.shift_responsibility import auto_assign_responsibility
from app.services.shifts import create_shift
from tests.helpers import create_node, create_soldier


def _make_shift(session, name_suffix: str, *, required_count: int, eligible_node_ids: list | None, start_date: date):
    dt = create_duty_type(session, name=f"dt_resp_{name_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_resp_{name_suffix}")
    session.add(loc)
    session.flush()
    shift = create_shift(
        session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start_date, end_date=date(start_date.year, start_date.month, start_date.day + 1),
        required_count=required_count, eligible_node_ids=eligible_node_ids,
    )
    session.flush()
    return shift


def test_picks_candidate_with_higher_potential_and_no_past_effort(admin_session):
    parent = create_node(admin_session, level="unit", name="resp_parent_1")
    strong = create_node(admin_session, level="branch", name="resp_strong", parent=parent)
    weak = create_node(admin_session, level="branch", name="resp_weak", parent=parent)
    for i in range(5):
        create_soldier(admin_session, personal_number=f"resp_strong_{i}", hierarchy_node_id=strong.id)
    create_soldier(admin_session, personal_number="resp_weak_0", hierarchy_node_id=weak.id)
    shift = _make_shift(admin_session, "1", required_count=2, eligible_node_ids=[parent.id], start_date=date(2026, 7, 1))
    admin_session.commit()

    result = auto_assign_responsibility(admin_session, shift_ids=[shift.id], reference_date=date(2026, 7, 1))

    assert len(result) == 1
    assert result[0].shift_id == shift.id
    assert result[0].node_name == "resp_strong"


def test_spreads_load_across_batch_when_candidates_tied(admin_session):
    parent = create_node(admin_session, level="unit", name="resp_parent_2")
    unit_a = create_node(admin_session, level="branch", name="resp_tied_a", parent=parent)
    unit_b = create_node(admin_session, level="branch", name="resp_tied_b", parent=parent)
    for i in range(3):
        create_soldier(admin_session, personal_number=f"resp_tied_a_{i}", hierarchy_node_id=unit_a.id)
        create_soldier(admin_session, personal_number=f"resp_tied_b_{i}", hierarchy_node_id=unit_b.id)
    shift_1 = _make_shift(admin_session, "2a", required_count=2, eligible_node_ids=[parent.id], start_date=date(2026, 7, 1))
    shift_2 = _make_shift(admin_session, "2b", required_count=2, eligible_node_ids=[parent.id], start_date=date(2026, 7, 2))
    admin_session.commit()

    result = auto_assign_responsibility(
        admin_session, shift_ids=[shift_1.id, shift_2.id], reference_date=date(2026, 7, 1)
    )

    by_shift = {r.shift_id: r.node_name for r in result}
    # Tied potential -> the first shift (processed by start_date order) picks either
    # unit deterministically; the second shift must pick the OTHER unit, since the
    # first unit's running_batch_load now makes it less attractive.
    assert by_shift[shift_1.id] != by_shift[shift_2.id]


def test_skips_shifts_with_no_eligible_node_ids(admin_session):
    shift = _make_shift(admin_session, "3", required_count=1, eligible_node_ids=None, start_date=date(2026, 7, 1))
    admin_session.commit()

    result = auto_assign_responsibility(admin_session, shift_ids=[shift.id], reference_date=date(2026, 7, 1))

    assert result == []
