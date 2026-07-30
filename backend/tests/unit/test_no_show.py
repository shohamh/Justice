from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyType, ScoreAdjustment
from app.services.no_show import NoShowError, count_no_shows, list_no_shows, mark_no_show
from tests.helpers import create_soldier


def _seed_past_assignment(session, *, personal_number="ns0001"):
    dt = DutyType(name=f"dt_{personal_number}", score_per_day=1)
    loc = DutyLocation(name=f"loc_{personal_number}")
    soldier = create_soldier(session, personal_number=personal_number)
    session.add_all([dt, loc])
    session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=5), end_date=date.today() - timedelta(days=4),
        status="published",
    )
    session.add(assignment)
    session.flush()
    return soldier, assignment


def test_mark_no_show_creates_record_and_score_penalty(admin_session):
    soldier, assignment = _seed_past_assignment(admin_session)
    marker = create_soldier(admin_session, personal_number="ns_marker1")
    record = mark_no_show(
        admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="לא הגיע לתורנות",
    )
    admin_session.commit()
    assert record.soldier_id == soldier.id
    assert record.marked_by == marker.id
    assert record.score_adjustment_id is not None
    adj = admin_session.get(ScoreAdjustment, record.score_adjustment_id)
    assert adj.soldier_id == soldier.id
    assert adj.delta == Decimal("-1")


def test_mark_no_show_rejects_empty_note(admin_session):
    soldier, assignment = _seed_past_assignment(admin_session, personal_number="ns0002")
    marker = create_soldier(admin_session, personal_number="ns_marker2")
    with pytest.raises(NoShowError, match="note_required"):
        mark_no_show(admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="")


def test_mark_no_show_rejects_future_duty(admin_session):
    dt = DutyType(name="dt_future_ns", score_per_day=1)
    loc = DutyLocation(name="loc_future_ns")
    soldier = create_soldier(admin_session, personal_number="ns0003")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=6),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.flush()
    marker = create_soldier(admin_session, personal_number="ns_marker3")
    with pytest.raises(NoShowError, match="duty_not_yet_finished"):
        mark_no_show(admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="x")


def test_mark_no_show_rejects_duplicate(admin_session):
    soldier, assignment = _seed_past_assignment(admin_session, personal_number="ns0004")
    marker = create_soldier(admin_session, personal_number="ns_marker4")
    mark_no_show(admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="ראשון")
    admin_session.flush()
    with pytest.raises(NoShowError, match="already_marked"):
        mark_no_show(admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="שני")


def test_count_and_list_no_shows(admin_session):
    soldier, assignment = _seed_past_assignment(admin_session, personal_number="ns0005")
    marker = create_soldier(admin_session, personal_number="ns_marker5")
    mark_no_show(admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="x")
    admin_session.commit()
    assert count_no_shows(admin_session, soldier_id=soldier.id) == 1
    records = list_no_shows(admin_session, soldier_id=soldier.id)
    assert len(records) == 1
    assert records[0].note == "x"
