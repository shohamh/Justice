import uuid
from datetime import date, timedelta

import pytest

from app.db.models import ExemptionType, SoldierExemption
from app.services.exemptions import (
    ExemptionError,
    active_exemptions,
    grant_exemption,
    list_exemptions,
    revoke_exemption,
)
from tests.helpers import create_soldier


def _et(session, name="פטור"):
    et = ExemptionType(name=name)
    session.add(et)
    session.flush()
    return et


def test_grant_exemption(admin_session):
    s = create_soldier(admin_session, personal_number="7300001")
    et = _et(admin_session, "פטור-1")
    ex = grant_exemption(
        admin_session,
        soldier_id=s.id,
        exemption_type_id=et.id,
        start_date=date(2026, 1, 1),
        end_date=None,
        reason="גב",
        actor_id=None,
    )
    admin_session.commit()
    assert ex.soldier_id == s.id
    assert ex.end_date is None


def test_grant_rejects_bad_date_range(admin_session):
    s = create_soldier(admin_session, personal_number="7300002")
    et = _et(admin_session, "פטור-2")
    with pytest.raises(ExemptionError):
        grant_exemption(
            admin_session,
            soldier_id=s.id,
            exemption_type_id=et.id,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 4, 1),
            reason=None,
            actor_id=None,
        )


def test_grant_rejects_unknown_soldier(admin_session):
    et = _et(admin_session, "פטור-3")
    with pytest.raises(ExemptionError):
        grant_exemption(
            admin_session,
            soldier_id=uuid.uuid4(),
            exemption_type_id=et.id,
            start_date=date(2026, 1, 1),
            end_date=None,
            reason=None,
            actor_id=None,
        )


def test_revoke_active_soft_sets_end_date_today_and_marks_revoked(admin_session):
    s = create_soldier(admin_session, personal_number="7300004")
    et = _et(admin_session, "פטור-4")
    ex = grant_exemption(
        admin_session,
        soldier_id=s.id,
        exemption_type_id=et.id,
        start_date=date.today() - timedelta(days=5),
        end_date=None,
        reason=None,
        actor_id=None,
    )
    admin_session.flush()
    actor = create_soldier(admin_session, personal_number="7300004a")
    revoke_exemption(admin_session, exemption_id=ex.id, reason="לא רלוונטי יותר", actor_id=actor.id)
    admin_session.commit()
    refreshed = admin_session.get(SoldierExemption, ex.id)
    assert refreshed is not None
    assert refreshed.end_date == date.today()
    assert refreshed.revoked_at is not None
    assert refreshed.revoked_by == actor.id
    assert refreshed.revoke_reason == "לא רלוונטי יותר"


def test_revoke_future_keeps_row_marks_revoked_not_deleted(admin_session):
    s = create_soldier(admin_session, personal_number="7300005")
    et = _et(admin_session, "פטור-5")
    original_start = date.today() + timedelta(days=10)
    ex = grant_exemption(
        admin_session,
        soldier_id=s.id,
        exemption_type_id=et.id,
        start_date=original_start,
        end_date=None,
        reason=None,
        actor_id=None,
    )
    admin_session.flush()
    ex_id = ex.id
    actor = create_soldier(admin_session, personal_number="7300005a")
    revoke_exemption(admin_session, exemption_id=ex_id, reason="בוטל לפני תחילה", actor_id=actor.id)
    admin_session.commit()
    refreshed = admin_session.get(SoldierExemption, ex_id)
    assert refreshed is not None  # no longer hard-deleted
    assert refreshed.start_date == original_start  # historical dates untouched
    assert refreshed.revoked_at is not None
    assert refreshed.revoked_by == actor.id
    assert refreshed.revoke_reason == "בוטל לפני תחילה"


def test_revoke_already_expired_is_noop(admin_session):
    s = create_soldier(admin_session, personal_number="7300008")
    et = _et(admin_session, "פטור-8")
    past_end = date.today() - timedelta(days=7)
    ex = grant_exemption(
        admin_session,
        soldier_id=s.id,
        exemption_type_id=et.id,
        start_date=date.today() - timedelta(days=30),
        end_date=past_end,
        reason=None,
        actor_id=None,
    )
    admin_session.flush()
    actor = create_soldier(admin_session, personal_number="7300008a")
    revoke_exemption(admin_session, exemption_id=ex.id, reason="ignored", actor_id=actor.id)
    admin_session.commit()
    refreshed = admin_session.get(SoldierExemption, ex.id)
    assert refreshed is not None
    assert refreshed.end_date == past_end  # unchanged, not pushed forward to today
    assert refreshed.revoked_at is None  # true no-op: nothing recorded
    assert refreshed.revoke_reason is None


def test_revoke_active_notifies_soldier(admin_session):
    from app.db.models import Notification, NotificationType
    from sqlalchemy import select as sa_select

    s = create_soldier(admin_session, personal_number="7300009")
    et = _et(admin_session, "פטור-9")
    ex = grant_exemption(
        admin_session,
        soldier_id=s.id,
        exemption_type_id=et.id,
        start_date=date.today() - timedelta(days=1),
        end_date=None,
        reason=None,
        actor_id=None,
    )
    admin_session.flush()
    actor = create_soldier(admin_session, personal_number="7300009a")
    revoke_exemption(admin_session, exemption_id=ex.id, reason="נבדק", actor_id=actor.id)
    admin_session.commit()

    notif = admin_session.execute(
        sa_select(Notification).where(
            Notification.soldier_id == s.id,
            Notification.type == NotificationType.exemption_revoked,
        )
    ).scalar_one_or_none()
    assert notif is not None


def test_active_exemptions_window(admin_session):
    s = create_soldier(admin_session, personal_number="7300006")
    et = _et(admin_session, "פטור-6")
    grant_exemption(
        admin_session,
        soldier_id=s.id,
        exemption_type_id=et.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        reason=None,
        actor_id=None,
    )
    grant_exemption(
        admin_session,
        soldier_id=s.id,
        exemption_type_id=et.id,
        start_date=date(2026, 3, 1),
        end_date=None,
        reason=None,
        actor_id=None,
    )
    admin_session.flush()
    on_jan = active_exemptions(admin_session, soldier_id=s.id, on_date=date(2026, 1, 15))
    on_feb = active_exemptions(admin_session, soldier_id=s.id, on_date=date(2026, 2, 15))
    on_apr = active_exemptions(admin_session, soldier_id=s.id, on_date=date(2026, 4, 1))
    assert len(on_jan) == 1
    assert len(on_feb) == 0
    assert len(on_apr) == 1  # the open-ended one


def test_list_exemptions(admin_session):
    s = create_soldier(admin_session, personal_number="7300007")
    et = _et(admin_session, "פטור-7")
    grant_exemption(
        admin_session,
        soldier_id=s.id,
        exemption_type_id=et.id,
        start_date=date(2026, 1, 1),
        end_date=None,
        reason=None,
        actor_id=None,
    )
    admin_session.flush()
    assert len(list_exemptions(admin_session, soldier_id=s.id)) == 1
