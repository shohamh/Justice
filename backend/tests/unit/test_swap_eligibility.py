from datetime import date

from app.db.models import (
    DutyAssignment, DutyLocation, DutyType, ExemptionDutyTypeMap,
    ExemptionType, PersonalConstraint, Soldier, SoldierExemption,
)
from app.services.eligibility import check_soldier_for_assignment


def _base(session):
    """Return (owner, cover, dt, loc, assignment).
    `assignment` belongs to `owner`. Tests check if `cover` can take it."""
    dt = DutyType(name="שמירה-elig", score_per_day=1)
    loc = DutyLocation(name="עמדה-elig")
    owner = Soldier(
        personal_number="elig-owner", full_name="Owner", password_hash="x",
        role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False,
    )
    cover = Soldier(
        personal_number="elig-cover", full_name="Cover", password_hash="x",
        role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False,
    )
    session.add_all([dt, loc, owner, cover])
    session.flush()
    a = DutyAssignment(
        soldier_id=owner.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 10), end_date=date(2026, 7, 10), status="published",
    )
    session.add(a)
    session.flush()
    return owner, cover, dt, loc, a


def test_eligible_when_no_restrictions(admin_session):
    _owner, cover, _dt, _loc, a = _base(admin_session)
    ok, reason = check_soldier_for_assignment(admin_session, cover.id, a.id)
    assert ok is True
    assert reason is None


def test_blocked_by_duty_type_eligibility(admin_session):
    _owner, cover, dt, _loc, a = _base(admin_session)
    dt.requirements = {"requires_mitvahim": True}  # cover has no last_mitvahim_date
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, cover.id, a.id)
    assert ok is False
    assert reason == "אי-כשירות לסוג תורנות זה"


def test_blocked_by_global_exemption(admin_session):
    _owner, cover, _dt, _loc, a = _base(admin_session)
    et = ExemptionType(name="פטור גלובלי", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(SoldierExemption(
        soldier_id=cover.id, exemption_type_id=et.id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31),
    ))
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, cover.id, a.id)
    assert ok is False
    assert reason == "פטור מסוג תורנות זו"


def test_blocked_by_duty_type_exemption(admin_session):
    _owner, cover, dt, _loc, a = _base(admin_session)
    et = ExemptionType(name="פטור שמירה", is_global=False)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt.id))
    admin_session.add(SoldierExemption(
        soldier_id=cover.id, exemption_type_id=et.id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 31),
    ))
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, cover.id, a.id)
    assert ok is False
    assert reason == "פטור מסוג תורנות זו"


def test_not_blocked_by_expired_exemption(admin_session):
    _owner, cover, _dt, _loc, a = _base(admin_session)
    et = ExemptionType(name="פטור ישן", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(SoldierExemption(
        soldier_id=cover.id, exemption_type_id=et.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 7, 9),  # ends before duty
    ))
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, cover.id, a.id)
    assert ok is True


def test_blocked_by_approved_constraint(admin_session):
    _owner, cover, _dt, _loc, a = _base(admin_session)
    admin_session.add(PersonalConstraint(
        soldier_id=cover.id, start_date=date(2026, 7, 8), end_date=date(2026, 7, 12),
        reason="חופש", status="approved",
    ))
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, cover.id, a.id)
    assert ok is False
    assert reason == "אילוץ אישי מאושר בתאריך זה"


def test_not_blocked_by_pending_constraint(admin_session):
    _owner, cover, _dt, _loc, a = _base(admin_session)
    admin_session.add(PersonalConstraint(
        soldier_id=cover.id, start_date=date(2026, 7, 8), end_date=date(2026, 7, 12),
        reason="חופש", status="pending",
    ))
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, cover.id, a.id)
    assert ok is True


def test_blocked_by_scheduling_conflict(admin_session):
    _owner, cover, dt, loc, a = _base(admin_session)
    # Give cover soldier an existing published duty on overlapping dates
    admin_session.add(DutyAssignment(
        soldier_id=cover.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 9), end_date=date(2026, 7, 11), status="published",
    ))
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, cover.id, a.id)
    assert ok is False
    assert reason == "שיבוץ קיים בתאריכים אלו"


def test_not_blocked_by_non_published_assignment(admin_session):
    _owner, cover, dt, loc, a = _base(admin_session)
    admin_session.add(DutyAssignment(
        soldier_id=cover.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 9), end_date=date(2026, 7, 11), status="algorithm_draft",
    ))
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, cover.id, a.id)
    assert ok is True


def test_not_blocked_by_back_to_back_assignment(admin_session):
    """A duty ending exactly when another begins (adjacent, not overlapping)
    must not be treated as a scheduling conflict. `a` runs 7/10-7/11 (exclusive
    end), so an existing duty 7/9-7/10 ends the moment `a` starts -- no overlap."""
    _owner, cover, dt, loc, _a = _base(admin_session)
    a = DutyAssignment(
        soldier_id=_owner.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 10), end_date=date(2026, 7, 11), status="published",
    )
    admin_session.add(a)
    admin_session.add(DutyAssignment(
        soldier_id=cover.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 9), end_date=date(2026, 7, 10), status="published",
    ))
    admin_session.flush()
    ok, reason = check_soldier_for_assignment(admin_session, cover.id, a.id)
    assert ok is True
    assert reason is None


def test_exclude_assignment_id_skips_conflict(admin_session):
    _owner, cover, dt, loc, a = _base(admin_session)
    conflict = DutyAssignment(
        soldier_id=cover.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 9), end_date=date(2026, 7, 11), status="published",
    )
    admin_session.add(conflict)
    admin_session.flush()
    # With exclusion — should pass
    ok, reason = check_soldier_for_assignment(
        admin_session, cover.id, a.id, exclude_assignment_id=conflict.id
    )
    assert ok is True
