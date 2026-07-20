from datetime import date

import pytest
from sqlalchemy import select

from app.db.models import (
    DutyDayOverride,
    DutyLocation,
    DutyType,
    ExemptionType,
    Notification,
    NotificationType,
    SoldierExemption,
)
from app.services.assignments import (
    AssignmentError,
    cancel_assignment,
    clear_day_override,
    create_assignment,
    list_assignments,
    list_assignments_for_soldiers,
    set_day_override,
)
from app.services.duty_config import map_exemption_to_duty_type
from tests.helpers import create_soldier


def _dt(session, name="dt", score="1.00"):
    from decimal import Decimal

    dt = DutyType(name=name, score_per_day=Decimal(score))
    session.add(dt)
    session.flush()
    return dt


def _loc(session, name="loc"):
    loc = DutyLocation(name=name)
    session.add(loc)
    session.flush()
    return loc


def test_create_assignment(admin_session):
    s = create_soldier(admin_session, personal_number="8100001")
    dt = _dt(admin_session, "שמירה-a1")
    loc = _loc(admin_session, "מוצב-a1")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
        notes="ok",
        actor_id=None,
    )
    admin_session.commit()
    assert a.status == "published"
    assert a.start_date == date(2026, 6, 1)


def test_create_rejects_bad_date_range(admin_session):
    s = create_soldier(admin_session, personal_number="8100002")
    dt = _dt(admin_session, "שמירה-a2")
    loc = _loc(admin_session, "מוצב-a2")
    with pytest.raises(AssignmentError):
        create_assignment(
            admin_session,
            soldier_id=s.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date(2026, 6, 5),
            end_date=date(2026, 6, 1),
            notes=None,
            actor_id=None,
        )


def test_create_rejects_overlap(admin_session):
    s = create_soldier(admin_session, personal_number="8100003")
    dt = _dt(admin_session, "שמירה-a3")
    loc = _loc(admin_session, "מוצב-a3")
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    with pytest.raises(AssignmentError) as exc:
        create_assignment(
            admin_session,
            soldier_id=s.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date(2026, 6, 4),
            end_date=date(2026, 6, 7),
            notes=None,
            actor_id=None,
        )
    assert "overlap" in str(exc.value)


def test_create_rejects_insufficient_rest_after_prior_duty(admin_session):
    s = create_soldier(admin_session, personal_number="8100010")
    dt = _dt(admin_session, "שמירה-rest1")
    loc = _loc(admin_session, "מוצב-rest1")
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), notes=None, actor_id=None,
    )
    admin_session.flush()
    # Prior assignment ends 23:59 on 06-01 (default end_time). New one starts
    # 00:00 on 06-02 (default start_time) — 1 minute gap, violates any rest > 0.
    from app.db.models import SystemSetting
    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    admin_session.flush()
    with pytest.raises(AssignmentError) as exc:
        create_assignment(
            admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date(2026, 6, 2), end_date=date(2026, 6, 3), notes=None, actor_id=None,
        )
    assert str(exc.value) == "insufficient_rest"


def test_create_allows_sufficient_rest_gap(admin_session):
    s = create_soldier(admin_session, personal_number="8100011")
    dt = _dt(admin_session, "שמירה-rest2")
    loc = _loc(admin_session, "מוצב-rest2")
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 5), end_date=date(2026, 6, 8), notes=None, actor_id=None,
    )
    admin_session.flush()
    from app.db.models import SystemSetting
    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    admin_session.flush()
    # Prior ends 23:59 on 06-07; new one starts 00:00 on 06-10 — plenty of gap.
    a = create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 12), notes=None, actor_id=None,
    )
    assert a.start_date == date(2026, 6, 10)


def test_create_rejects_exempted_soldier(admin_session):
    s = create_soldier(admin_session, personal_number="8100004")
    dt = _dt(admin_session, "שמירה-a4")
    loc = _loc(admin_session, "מוצב-a4")
    et = ExemptionType(name="פטור-a4")
    admin_session.add(et)
    admin_session.flush()
    map_exemption_to_duty_type(
        admin_session, exemption_type_id=et.id, duty_type_id=dt.id, actor_id=None
    )
    admin_session.add(
        SoldierExemption(
            soldier_id=s.id, exemption_type_id=et.id, start_date=date(2026, 6, 1), end_date=None
        )
    )
    admin_session.flush()
    with pytest.raises(AssignmentError) as exc:
        create_assignment(
            admin_session,
            soldier_id=s.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date(2026, 6, 2),
            end_date=date(2026, 6, 4),
            notes=None,
            actor_id=None,
        )
    assert "exempted" in str(exc.value)


def test_cancel_assignment(admin_session):
    s = create_soldier(admin_session, personal_number="8100005")
    dt = _dt(admin_session, "שמירה-a5")
    loc = _loc(admin_session, "מוצב-a5")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    cancel_assignment(admin_session, assignment=a, reason="בוטל", actor_id=None)
    admin_session.commit()
    assert a.status == "cancelled"
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        notes=None,
        actor_id=None,
    )
    admin_session.commit()


def test_cancel_requires_reason(admin_session):
    s = create_soldier(admin_session, personal_number="8100006")
    dt = _dt(admin_session, "שמירה-a6")
    loc = _loc(admin_session, "מוצב-a6")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    with pytest.raises(AssignmentError):
        cancel_assignment(admin_session, assignment=a, reason="  ", actor_id=None)


def test_set_and_clear_day_override(admin_session):
    s = create_soldier(admin_session, personal_number="8200001")
    repl = create_soldier(admin_session, personal_number="8200002")
    dt = _dt(admin_session, "שמירה-o1")
    loc = _loc(admin_session, "מוצב-o1")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 5),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    ov = set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 7, 3),
        effective_soldier_id=repl.id,
        reason="replacement",
        actor_id=None,
    )
    admin_session.flush()
    assert ov.effective_soldier_id == repl.id
    clear_day_override(admin_session, assignment=a, date=date(2026, 7, 3), actor_id=None)
    admin_session.flush()
    assert (
        admin_session.execute(
            select(DutyDayOverride).where(DutyDayOverride.duty_assignment_id == a.id)
        ).first()
        is None
    )


def test_override_cancel_day_with_null_effective(admin_session):
    s = create_soldier(admin_session, personal_number="8200003")
    dt = _dt(admin_session, "שמירה-o2")
    loc = _loc(admin_session, "מוצב-o2")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    ov = set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 7, 1),
        effective_soldier_id=None,
        reason="cancelled",
        actor_id=None,
    )
    admin_session.flush()
    assert ov.effective_soldier_id is None


def test_override_rejects_date_out_of_range(admin_session):
    s = create_soldier(admin_session, personal_number="8200004")
    dt = _dt(admin_session, "שמירה-o3")
    loc = _loc(admin_session, "מוצב-o3")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    with pytest.raises(AssignmentError):
        set_day_override(
            admin_session,
            assignment=a,
            date=date(2026, 7, 9),
            effective_soldier_id=None,
            reason="cancelled",
            actor_id=None,
        )


def test_set_override_is_idempotent_upsert(admin_session):
    s = create_soldier(admin_session, personal_number="8200005")
    r1 = create_soldier(admin_session, personal_number="8200006")
    r2 = create_soldier(admin_session, personal_number="8200007")
    dt = _dt(admin_session, "שמירה-o4")
    loc = _loc(admin_session, "מוצב-o4")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 7, 1),
        effective_soldier_id=r1.id,
        reason="replacement",
        actor_id=None,
    )
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 7, 1),
        effective_soldier_id=r2.id,
        reason="replacement",
        actor_id=None,
    )
    admin_session.flush()
    rows = (
        admin_session.execute(
            select(DutyDayOverride).where(DutyDayOverride.duty_assignment_id == a.id)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].effective_soldier_id == r2.id


def test_set_day_override_new_notifies_only_replacement(admin_session):
    s = create_soldier(admin_session, personal_number="8200010")
    repl = create_soldier(admin_session, personal_number="8200011")
    dt = _dt(admin_session, "שמירה-n1")
    loc = _loc(admin_session, "מוצב-n1")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 5),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 7, 3),
        effective_soldier_id=repl.id,
        reason="replacement",
        actor_id=None,
    )
    admin_session.flush()
    removed = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == s.id,
            Notification.type == NotificationType.assignment_removed,
        )
    ).first()
    created = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == repl.id,
            Notification.type == NotificationType.assignment_created,
        )
    ).first()
    assert removed is None
    assert created is not None


def test_set_day_override_change_notifies_both_old_and_new(admin_session):
    s = create_soldier(admin_session, personal_number="8200012")
    r1 = create_soldier(admin_session, personal_number="8200013")
    r2 = create_soldier(admin_session, personal_number="8200014")
    dt = _dt(admin_session, "שמירה-n2")
    loc = _loc(admin_session, "מוצב-n2")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 5),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 7, 3),
        effective_soldier_id=r1.id,
        reason="replacement",
        actor_id=None,
    )
    admin_session.flush()
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 7, 3),
        effective_soldier_id=r2.id,
        reason="replacement",
        actor_id=None,
    )
    admin_session.flush()
    removed = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == r1.id,
            Notification.type == NotificationType.assignment_removed,
        )
    ).first()
    created = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == r2.id,
            Notification.type == NotificationType.assignment_created,
        )
    ).first()
    assert removed is not None
    assert created is not None


def test_clear_day_override_notifies_old_soldier_as_removed(admin_session):
    s = create_soldier(admin_session, personal_number="8200015")
    repl = create_soldier(admin_session, personal_number="8200016")
    dt = _dt(admin_session, "שמירה-n3")
    loc = _loc(admin_session, "מוצב-n3")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 5),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 7, 3),
        effective_soldier_id=repl.id,
        reason="replacement",
        actor_id=None,
    )
    admin_session.flush()
    clear_day_override(admin_session, assignment=a, date=date(2026, 7, 3), actor_id=None)
    admin_session.flush()
    removed = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == repl.id,
            Notification.type == NotificationType.assignment_removed,
        )
    ).first()
    assert removed is not None


def test_list_assignments_by_soldier_and_range(admin_session):
    s = create_soldier(admin_session, personal_number="8200008")
    dt = _dt(admin_session, "שמירה-o5")
    loc = _loc(admin_session, "מוצב-o5")
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        notes=None,
        actor_id=None,
    )
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    july = list_assignments(
        admin_session, soldier_id=s.id, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)
    )
    assert len(july) == 1
    both = list_assignments_for_soldiers(admin_session, soldier_ids=[s.id])
    assert len(both) == 2
