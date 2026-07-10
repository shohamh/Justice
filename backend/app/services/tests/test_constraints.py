from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.helpers import create_soldier


def test_submit_constraint_rejects_span_over_364_days(admin_session):
    from app.services.constraints import submit_constraint, ConstraintError
    from app.services.settings_loader import set_setting

    soldier = create_soldier(admin_session, personal_number="7910004")
    # Raise the personal cap so the 364-day check is what actually fires here,
    # not the pre-existing (lower, default 15-day) constraints.personal_cap_days cap.
    set_setting(admin_session, "constraints.personal_cap_days", 10000, actor_id=None)
    admin_session.commit()

    start = date.today() + timedelta(days=1)
    with pytest.raises(ConstraintError, match="date_range_too_long"):
        submit_constraint(
            admin_session, soldier_id=soldier.id,
            start_date=start, end_date=start + timedelta(days=365), reason="test",
        )
