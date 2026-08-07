from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyType,
    Notification,
    NotificationType,
    RangeAttendanceStatus,
    RangeType,
    ScoreAdjustment,
    SoldierRangeQualification,
)
from app.services.ranges import (
    RangeValidationError,
    add_range_assignment,
    cancel_range_event,
    create_range_event,
    mark_attendance,
)
from app.services.settings_loader import apply_settings
from tests.helpers import create_node, create_range_location, create_soldier


def _setup_event_and_assignment(session: Session, *, event_date: date, range_type: RangeType = RangeType.laser):
    node = create_node(session, level="פלוגה", name=f"פלוגה-{event_date}")
    weapon_duty = DutyType(
        name=f"שמירה עם נשק {event_date}", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    session.add(weapon_duty)
    session.flush()
    soldier = create_soldier(session, personal_number=f"5{event_date.toordinal()}"[:10], hierarchy_node_id=node.id)
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=range_type,
        event_date=event_date, range_location_id=create_range_location(session, name="מטווח").id, required_count=1,
    )
    assignment = add_range_assignment(session, event=event, soldier_id=soldier.id, is_reserve=False)
    return event, soldier, assignment


def test_mark_present_updates_qualification(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)

    updated = mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    assert updated.attendance_status == RangeAttendanceStatus.present
    qualification = app_session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id == soldier.id,
            SoldierRangeQualification.range_type == RangeType.laser,
        )
    ).scalar_one()
    assert qualification.valid_until == past_date + timedelta(days=180)


def test_mark_no_show_requires_note(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)

    with pytest.raises(RangeValidationError):
        mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.no_show, marked_by=soldier.id)


def test_mark_no_show_creates_score_adjustment_and_audit(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)

    updated = mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="לא הגיע ללא הודעה מוקדמת",
    )

    assert updated.attendance_status == RangeAttendanceStatus.no_show
    assert updated.score_adjustment_id is not None


def test_mark_no_show_notifies_manager_once_with_range_context(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    node = create_node(app_session, level="×¤×œ×•×’×”", name="×¤×œ×•×’×” ××™×¨×•×¢")
    manager = create_soldier(app_session, personal_number="5900002", role="duty_manager", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="×©×ž×™×¨×” ×¢× × ×©×§ ××™×¨×•×¢", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()
    soldier = create_soldier(app_session, personal_number="5900003", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=past_date, range_location_id=create_range_location(app_session, name="×ž×˜×•×•×— ××™×¨×•×¢").id, required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
                    marked_by=manager.id, note="×œ× ×”×•×¤×™×¢")
    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
                    marked_by=manager.id, note="×œ× ×”×•×¤×™¢ ×©×•×‘")

    notifications = app_session.execute(select(Notification).where(
        Notification.soldier_id == manager.id,
        Notification.type == NotificationType.range_no_show,
        Notification.reference_type == "range_event",
        Notification.reference_id == event.id,
    )).scalars().all()
    assert len(notifications) == 1
    assert "reason=" in (notifications[0].body or "")

def test_mark_present_rejects_draft_before_creating_qualification(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    _event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    assignment.is_draft = True
    app_session.commit()

    with pytest.raises(RangeValidationError, match="assignment_not_confirmed"):
        mark_attendance(
            app_session,
            assignment=assignment,
            status=RangeAttendanceStatus.present,
            marked_by=soldier.id,
        )

    assert assignment.attendance_status == RangeAttendanceStatus.pending
    qualification_count = app_session.execute(
        select(func.count()).select_from(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id == soldier.id
        )
    ).scalar_one()
    assert qualification_count == 0


def test_mark_no_show_rejects_draft_before_score_or_notification_side_effects(
    app_session: Session,
) -> None:
    past_date = date.today() - timedelta(days=1)
    _event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    assignment.is_draft = True
    app_session.commit()
    score_count_before = app_session.execute(
        select(func.count()).select_from(ScoreAdjustment).where(ScoreAdjustment.soldier_id == soldier.id)
    ).scalar_one()
    notification_count_before = app_session.execute(
        select(func.count()).select_from(Notification).where(Notification.soldier_id == soldier.id)
    ).scalar_one()

    with pytest.raises(RangeValidationError, match="assignment_not_confirmed"):
        mark_attendance(
            app_session,
            assignment=assignment,
            status=RangeAttendanceStatus.no_show,
            marked_by=soldier.id,
            note="לא הגיע",
        )

    assert assignment.attendance_status == RangeAttendanceStatus.pending
    score_count_after = app_session.execute(
        select(func.count()).select_from(ScoreAdjustment).where(ScoreAdjustment.soldier_id == soldier.id)
    ).scalar_one()
    notification_count_after = app_session.execute(
        select(func.count()).select_from(Notification).where(Notification.soldier_id == soldier.id)
    ).scalar_one()
    assert score_count_after == score_count_before
    assert notification_count_after == notification_count_before


def test_mark_attendance_rejects_future_event(app_session: Session) -> None:
    future_date = date.today() + timedelta(days=10)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=future_date)

    with pytest.raises(RangeValidationError):
        mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)


def test_mark_attendance_rejects_cancelled_event(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    cancel_range_event(app_session, event=event, reason="test cancellation")

    with pytest.raises(RangeValidationError):
        mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)


def test_correcting_present_to_no_show_reverses_qualification_and_applies_penalty(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    corrected = mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="תיקון בדיעבד - לא היה נוכח",
    )

    assert corrected.attendance_status == RangeAttendanceStatus.no_show
    assert corrected.score_adjustment_id is not None
    from app.services.ranges import get_effective_range_qualification

    assert get_effective_range_qualification(
        app_session, soldier_id=soldier.id, range_type=RangeType.laser
    ) is None


def test_correcting_no_show_to_present_reverses_penalty_and_sets_qualification(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="סימון ראשוני",
    )

    corrected = mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.present,
        marked_by=soldier.id, note="התברר שהוא כן הגיע",
    )

    assert corrected.attendance_status == RangeAttendanceStatus.present
    assert corrected.score_adjustment_id is None
    qualification = app_session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id == soldier.id,
            SoldierRangeQualification.range_type == RangeType.laser,
        )
    ).scalar_one()
    assert qualification.valid_until == past_date + timedelta(days=180)


def test_correcting_newer_present_to_no_show_preserves_older_still_valid_qualification(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    older_date = date.today() - timedelta(days=10)
    newer_date = date.today() - timedelta(days=1)
    node = create_node(app_session, level="פלוגה", name="פלוגה היסטוריה")
    weapon_duty = DutyType(name="שמירה עם נשק היסטוריה", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[node.id])
    app_session.add(weapon_duty)
    app_session.flush()
    soldier = create_soldier(app_session, personal_number="5900001", hierarchy_node_id=node.id)

    event_a = create_range_event(app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
                                  event_date=older_date, range_location_id=create_range_location(app_session, name="מטווח א").id, required_count=1)
    assignment_a = add_range_assignment(app_session, event=event_a, soldier_id=soldier.id, is_reserve=False)
    mark_attendance(app_session, assignment=assignment_a, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    event_b = create_range_event(app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
                                  event_date=newer_date, range_location_id=create_range_location(app_session, name="מטווח ב").id, required_count=1)
    assignment_b = add_range_assignment(app_session, event=event_b, soldier_id=soldier.id, is_reserve=False)
    mark_attendance(app_session, assignment=assignment_b, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    mark_attendance(app_session, assignment=assignment_b, status=RangeAttendanceStatus.no_show,
                     marked_by=soldier.id, note="תיקון - לא היה נוכח במטווח ב")

    from app.services.ranges import get_effective_range_qualification
    effective = get_effective_range_qualification(app_session, soldier_id=soldier.id, range_type=RangeType.laser)
    assert effective == older_date + timedelta(days=180)


def test_correcting_no_show_to_present_actually_reverses_the_score_penalty(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
                     marked_by=soldier.id, note="סימון ראשוני")

    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.present,
        marked_by=soldier.id, note="התברר שכן הגיע",
    )

    total = app_session.execute(
        select(func.coalesce(func.sum(ScoreAdjustment.delta), 0)).where(ScoreAdjustment.soldier_id == soldier.id)
    ).scalar_one()
    assert total == 0


def test_reversal_delta_negates_actual_original_delta_not_a_constant(app_session: Session) -> None:
    """The compensating reversal must negate whatever delta was ACTUALLY stored on
    the original ScoreAdjustment row, not a hardcoded/constant-derived value. To
    prove this, we mutate the original adjustment's delta to a non-default value
    (simulating e.g. a manual admin correction after the fact) before triggering
    the reversal - a hardcoded -_NO_SHOW_PENALTY-style implementation would still
    produce the constant's negation here and fail this assertion."""
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
                     marked_by=soldier.id, note="סימון ראשוני")

    original_adjustment = app_session.get(ScoreAdjustment, assignment.score_adjustment_id)
    assert original_adjustment is not None
    original_adjustment.delta = Decimal("-3")
    app_session.flush()

    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.present,
        marked_by=soldier.id, note="התברר שכן הגיע",
    )

    reversal = app_session.execute(
        select(ScoreAdjustment).where(
            ScoreAdjustment.soldier_id == soldier.id,
            ScoreAdjustment.reason == "range_no_show_reversed",
        )
    ).scalar_one()
    assert reversal.delta == Decimal("3")


def test_correcting_no_show_to_present_without_note_raises(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="סימון ראשוני",
    )

    with pytest.raises(RangeValidationError, match="note_required_for_attendance_change"):
        mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)


def test_pending_to_present_still_does_not_require_note(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)

    updated = mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    assert updated.attendance_status == RangeAttendanceStatus.present


def test_no_show_notifies_direct_commander(app_session: Session) -> None:
    from app.db.models import HierarchyNode

    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    past_date = date.today() - timedelta(days=1)
    commander = create_soldier(app_session, personal_number="5900010", role="commander")
    node = create_node(app_session, level="פלוגה", name="פלוגה-מפקד", commander_id=commander.id)
    app_session.commit()
    weapon_duty = DutyType(
        name="שמירה עם נשק מפקד", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=past_date, range_location_id=create_range_location(app_session, name="מטווח מפקד").id,
        required_count=1,
    )
    soldier = create_soldier(app_session, personal_number="5900011", hierarchy_node_id=node.id)
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=commander.id, note="לא הגיע",
    )

    notif = app_session.execute(select(Notification).where(
        Notification.soldier_id == commander.id,
        Notification.type == NotificationType.range_absence_reported_to_commander,
    )).scalar_one()
    assert notif.body == "לא הגיע"


def test_correcting_to_present_notifies_soldier_and_commander(app_session: Session) -> None:
    from app.db.models import HierarchyNode

    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    past_date = date.today() - timedelta(days=1)
    commander = create_soldier(app_session, personal_number="5900012", role="commander")
    node = create_node(app_session, level="פלוגה", name="פלוגה-מפקד-2", commander_id=commander.id)
    app_session.commit()
    weapon_duty = DutyType(
        name="שמירה עם נשק מפקד 2", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=past_date, range_location_id=create_range_location(app_session, name="מטווח מפקד 2").id,
        required_count=1,
    )
    soldier = create_soldier(app_session, personal_number="5900013", hierarchy_node_id=node.id)
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=commander.id, note="סימון ראשוני",
    )

    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.present,
        marked_by=commander.id, note="התברר שכן הגיע",
    )

    for recipient_id in (soldier.id, commander.id):
        notif = app_session.execute(select(Notification).where(
            Notification.soldier_id == recipient_id,
            Notification.type == NotificationType.range_attendance_corrected_to_present,
        )).scalar_one()
        assert notif.body == "התברר שכן הגיע"


def test_no_direct_commander_does_not_raise(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    node = create_node(app_session, level="פלוגה", name="פלוגה-ללא-מפקד")
    weapon_duty = DutyType(
        name="שמירה עם נשק ללא מפקד", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=past_date, range_location_id=create_range_location(app_session, name="מטווח ללא מפקד").id,
        required_count=1,
    )
    soldier = create_soldier(app_session, personal_number="5900014", hierarchy_node_id=node.id)
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    updated = mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="לא הגיע",
    )
    assert updated.attendance_status == RangeAttendanceStatus.no_show


def test_auto_mark_uses_none_marked_by(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)

    updated = mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=None)

    assert updated.marked_by is None
    assert updated.attendance_status == RangeAttendanceStatus.present
