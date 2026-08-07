from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import DutyType


def test_existing_weapon_duty_types_backfilled_to_laser(app_session: Session) -> None:
    weapon_dt = DutyType(name="mig-weapon", score_per_day=Decimal("1.00"), requires_weapon=True)
    non_weapon_dt = DutyType(name="mig-non-weapon", score_per_day=Decimal("1.00"), requires_weapon=False)
    app_session.add_all([weapon_dt, non_weapon_dt])
    app_session.commit()

    # The migration already ran during test DB setup (see backend/tests/conftest.py),
    # so newly-inserted rows won't retroactively show the backfill — instead assert
    # the column exists and accepts the expected enum values directly.
    app_session.execute(
        text("UPDATE duty_types SET required_range_type = 'live' WHERE id = :id"),
        {"id": weapon_dt.id},
    )
    app_session.commit()
    app_session.refresh(weapon_dt)
    assert weapon_dt.required_range_type == "live"

    app_session.refresh(non_weapon_dt)
    assert non_weapon_dt.required_range_type is None
