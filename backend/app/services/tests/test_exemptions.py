from __future__ import annotations

import uuid
from datetime import date

import pytest

from sqlalchemy import select

from app.db.models import ExemptionType, Notification, NotificationType, Soldier
from app.services.exemptions import (
    ExemptionError, grant_commander_exemption, grant_exemption, revoke_exemption,
)


def _soldier(session, **kw):
    s = Soldier(personal_number=str(uuid.uuid4())[:8], full_name="X", password_hash="x", **kw)
    session.add(s)
    session.flush()
    return s


def test_grant_commander_exemption_rejects_regular_type(app_session):
    et = ExemptionType(name="פטור רפואי", is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    granter = _soldier(app_session, rank="רסן")
    with pytest.raises(ExemptionError, match="not_commander_exemption_type"):
        grant_commander_exemption(
            app_session, soldier_id=soldier.id, exemption_type_id=et.id,
            start_date=date(2026, 1, 1), reason="test", actor_id=granter.id,
        )


def test_grant_commander_exemption_rejects_bad_date_range(app_session):
    et = ExemptionType(name="פטור פיקודי 2", is_commander_exemption=True)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    granter = _soldier(app_session, rank="רסן")
    with pytest.raises(ExemptionError, match="bad_date_range"):
        grant_commander_exemption(
            app_session, soldier_id=soldier.id, exemption_type_id=et.id,
            start_date=date(2026, 1, 10), end_date=date(2026, 1, 1),
            reason="test", actor_id=granter.id,
        )


def test_grant_commander_exemption_succeeds_for_commander_type(app_session):
    et = ExemptionType(name="פטור פיקודי", is_commander_exemption=True)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    granter = _soldier(app_session, rank="רסן")
    ex = grant_commander_exemption(
        app_session, soldier_id=soldier.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), reason="special case", actor_id=granter.id,
    )
    assert ex.exemption_type_id == et.id
    assert ex.granted_by == granter.id


def test_grant_exemption_notification_includes_type_name_and_dates(app_session):
    et = ExemptionType(name="חופשה")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    granter = _soldier(app_session, rank="רסן")
    ex = grant_exemption(
        app_session, soldier_id=soldier.id, exemption_type_id=et.id,
        start_date=date(2026, 8, 10), end_date=date(2026, 8, 15),
        reason="אירוע משפחתי", actor_id=granter.id,
    )
    notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.reference_id == ex.id,
            Notification.type == NotificationType.exemption_approved,
        )
    ).scalar_one()
    assert "חופשה" in notif.title
    assert "2026-08-10" in notif.title and "2026-08-15" in notif.title
    assert notif.body == "אירוע משפחתי"


def test_grant_commander_exemption_notification_includes_type_name_and_dates(app_session):
    et = ExemptionType(name="פטור פיקודי", is_commander_exemption=True)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    granter = _soldier(app_session, rank="רסן")
    ex = grant_commander_exemption(
        app_session, soldier_id=soldier.id, exemption_type_id=et.id,
        start_date=date(2026, 8, 10), end_date=date(2026, 8, 15),
        reason="special case", actor_id=granter.id,
    )
    notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.reference_id == ex.id,
            Notification.type == NotificationType.exemption_approved,
        )
    ).scalar_one()
    assert "פטור פיקודי" in notif.title
    assert "2026-08-10" in notif.title and "2026-08-15" in notif.title


def test_revoke_exemption_notification_includes_type_name_and_dates(app_session):
    et = ExemptionType(name="רפואי")
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    granter = _soldier(app_session, rank="רסן")
    ex = grant_exemption(
        app_session, soldier_id=soldier.id, exemption_type_id=et.id,
        start_date=date(2026, 12, 1), end_date=date(2026, 12, 31),
        reason="x", actor_id=granter.id,
    )
    revoke_exemption(app_session, exemption_id=ex.id, reason="התגייס מחדש", actor_id=granter.id)
    notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.reference_id == ex.id,
            Notification.type == NotificationType.exemption_revoked,
        )
    ).scalar_one()
    assert "רפואי" in notif.title
    assert "2026-12-01" in notif.title and "2026-12-31" in notif.title
