from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.db.models import ExemptionType, Soldier
from app.services.exemptions import ExemptionError, grant_commander_exemption


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
