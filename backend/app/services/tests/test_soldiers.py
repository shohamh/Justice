from __future__ import annotations

from datetime import date, timedelta

import pytest


def test_update_soldier_profile_rejects_discharge_before_enlistment(admin_session):
    from app.services.soldiers import update_soldier_profile, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920001")
    soldier.enlistment_date = date(2024, 1, 1)
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="discharge_date"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"discharge_date": date(2023, 1, 1)}, actor_id=None,
        )


def test_update_soldier_profile_rejects_mandatory_end_after_discharge(admin_session):
    from app.services.soldiers import update_soldier_profile, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920002")
    soldier.enlistment_date = date(2024, 1, 1)
    soldier.discharge_date = date(2026, 1, 1)
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="mandatory_end_date"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"mandatory_end_date": date(2026, 6, 1)}, actor_id=None,
        )


def test_update_soldier_profile_rejects_career_discharge_in_past(admin_session):
    from app.services.soldiers import update_soldier_profile, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920003")
    # mandatory_end_date in the past -> is_career derives to True on the update below,
    # so the cross-field check has something real to reject.
    soldier.mandatory_end_date = date(2020, 6, 1)
    soldier.enlistment_date = date(2020, 1, 1)
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="career"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"discharge_date": date.today() - timedelta(days=1)}, actor_id=None,
        )


def test_update_soldier_profile_allows_valid_dates(admin_session):
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920004")
    soldier.enlistment_date = date(2024, 1, 1)
    admin_session.commit()

    # Both dates in the future -> is_career derives to False, so this exercises pure
    # date-ordering validation without tripping the "career + past discharge" check.
    mandatory_end = date.today() + timedelta(days=30)
    discharge = date.today() + timedelta(days=400)
    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"discharge_date": discharge, "mandatory_end_date": mandatory_end},
        actor_id=None,
    )
    assert soldier.discharge_date == discharge


def test_update_soldier_profile_rejects_chovah_only_rank_while_career(admin_session):
    from app.services.soldiers import update_soldier_profile, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920010")
    soldier.mandatory_end_date = date(2020, 1, 1)  # long past -> derives to קבע
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="rank"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"rank": "טוראי"}, actor_id=None,
        )


def test_update_soldier_profile_derives_is_career_from_dates(admin_session):
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920011")
    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"rank": "רסן", "mandatory_end_date": date(2020, 1, 1)}, actor_id=None,
    )
    assert soldier.is_career is True


def test_approve_field_update_rejects_discharge_before_enlistment(admin_session):
    from app.services.soldiers import submit_field_update, approve_field_update, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920005")
    soldier.enlistment_date = date(2024, 1, 1)
    admin_session.commit()

    upd = submit_field_update(
        admin_session, soldier_id=soldier.id, field_name="discharge_date",
        new_value="2023-01-01", actor_id=soldier.id,
    )
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="discharge_date"):
        approve_field_update(admin_session, update=upd, actor_id=soldier.id)
