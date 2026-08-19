import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyAssignment, DutyLocation, DutyType
from app.services.scoring import effective_duty_spans, shift_count_by_soldier, swap_surface_duty_spans
from tests.helpers import create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _assignment(session, *, soldier_id, status):
    dt = DutyType(name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    session.add_all([dt, loc])
    session.flush()
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=6),
        status=status,
    )
    session.add(a)
    session.flush()
    return a


def test_draft_assignment_excluded_from_effective_duty_spans(admin_session):
    node = create_node(admin_session, level="unit", name=f"scoring-swap-{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"77200{_uid()[:3]}", hierarchy_node_id=node.id)
    _assignment(admin_session, soldier_id=soldier.id, status="algorithm_draft")

    spans = effective_duty_spans(admin_session, soldier_ids={soldier.id})

    assert spans == []


def test_draft_assignment_included_in_swap_surface_duty_spans(admin_session):
    node = create_node(admin_session, level="unit", name=f"scoring-swap-{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"77201{_uid()[:3]}", hierarchy_node_id=node.id)
    a = _assignment(admin_session, soldier_id=soldier.id, status="algorithm_draft")

    spans = swap_surface_duty_spans(admin_session, soldier_ids={soldier.id})

    assert len(spans) == 1
    assert spans[0]["assignment_id"] == a.id
    assert spans[0]["soldier_id"] == soldier.id


def test_published_assignment_present_in_both(admin_session):
    node = create_node(admin_session, level="unit", name=f"scoring-swap-{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"77202{_uid()[:3]}", hierarchy_node_id=node.id)
    a = _assignment(admin_session, soldier_id=soldier.id, status="published")

    eff_spans = effective_duty_spans(admin_session, soldier_ids={soldier.id})
    swap_spans = swap_surface_duty_spans(admin_session, soldier_ids={soldier.id})

    assert len(eff_spans) == 1 and eff_spans[0]["assignment_id"] == a.id
    assert len(swap_spans) == 1 and swap_spans[0]["assignment_id"] == a.id


def test_shift_count_by_soldier_ignores_drafts(admin_session):
    node = create_node(admin_session, level="unit", name=f"scoring-swap-{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"77203{_uid()[:3]}", hierarchy_node_id=node.id)
    _assignment(admin_session, soldier_id=soldier.id, status="algorithm_draft")

    counts = shift_count_by_soldier(admin_session)

    assert counts.get(soldier.id, 0) == 0
