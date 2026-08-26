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

    with pytest.raises(SoldierValidationError, match="mandatory_end_after_discharge"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"mandatory_end_date": date(2026, 6, 1)}, actor_id=None,
        )


def test_update_soldier_profile_rejects_mandatory_end_before_enlistment(admin_session):
    from app.services.soldiers import update_soldier_profile, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920006")
    soldier.enlistment_date = date(2024, 1, 1)
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="mandatory_end_before_enlistment"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"mandatory_end_date": date(2023, 6, 1)}, actor_id=None,
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
    # An explicit discharge_date after mandatory_end_date is the genuine
    # inconsistency this check targets. A soldier with mandatory_end_date in the
    # past but no discharge_date yet is simply still serving and must NOT be
    # rejected (see test_chovah_private_with_past_mandatory_end_and_no_discharge_date_is_allowed).
    soldier.discharge_date = date(2020, 6, 1)
    admin_session.commit()

    with pytest.raises(SoldierValidationError, match="rank"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"rank": "טוראי"}, actor_id=None,
        )


def test_chovah_private_with_past_mandatory_end_and_no_discharge_date_is_allowed():
    """A currently-serving טוראי whose mandatory_end_date field is in the past
    but who has no discharge_date yet (i.e. still serving, discharge just not
    logged) must NOT be rejected as an inconsistent 'chovah rank cannot be keva'.
    """
    from app.services.soldiers import _check_soldier_dates

    past_end = date.today() - timedelta(days=10)
    # Should not raise.
    _check_soldier_dates(
        rank="טוראי",
        enlistment_date=date.today() - timedelta(days=400),
        discharge_date=None,
        mandatory_end_date=past_end,
        is_career=False,
    )


def test_chovah_private_with_explicit_inconsistent_discharge_date_still_rejected():
    """If a discharge_date IS provided and it's after mandatory_end_date for a
    CHOVAH-only rank, that's a genuine inconsistency and must still be rejected.
    """
    from app.services.soldiers import _check_soldier_dates, SoldierValidationError

    past_end = date.today() - timedelta(days=10)
    later_discharge = date.today() + timedelta(days=5)
    with pytest.raises(SoldierValidationError):
        _check_soldier_dates(
            rank="טוראי",
            enlistment_date=date.today() - timedelta(days=400),
            discharge_date=later_discharge,
            mandatory_end_date=past_end,
            is_career=False,
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


def test_update_soldier_profile_persists_academic_track_for_shared_rank(admin_session):
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920012")
    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={
            "rank": "סרן",
            "rank_track": "officer_academic",
            "mandatory_end_date": date(2020, 1, 1),
            "discharge_date": date(2030, 1, 1),
        }, actor_id=None,
    )

    assert soldier.rank_track == "officer_academic"


def test_update_soldier_profile_allows_unrelated_edit_on_grandfathered_bad_rank_track(admin_session):
    """A pre-existing soldier row with an incompatible rank/track combo (e.g.
    created before validate_rank_track_compatibility existed) must not be
    permanently locked out of unrelated edits like phone. Only a PATCH that
    actually touches rank/mandatory_end_date/discharge_date should re-validate
    the rank/track combination.
    """
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920020")
    # סרן is קבע-only, but is_career derives to False here because
    # mandatory_end_date is None -> a grandfathered-bad combination that
    # predates this validation.
    soldier.rank = "סרן"
    soldier.is_career = False
    admin_session.commit()

    # Editing an unrelated field must succeed, not be blocked by the
    # pre-existing bad combination.
    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"phone": "0501234567"}, actor_id=None,
    )
    assert soldier.phone == "0501234567"
    # The bad combination is untouched (not silently "fixed" either).
    assert soldier.rank == "סרן"
    assert soldier.is_career is False


def test_update_soldier_profile_rejects_new_incompatible_rank_track(admin_session):
    """Editing rank into a genuinely new incompatible combination must still
    be rejected, even for a soldier who previously had a grandfathered bad
    combination."""
    from app.services.soldiers import update_soldier_profile, SoldierValidationError
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920021")
    soldier.rank = "סרן"
    soldier.is_career = False
    admin_session.commit()

    # Actively moving the soldier's rank while still חובה (no mandatory_end_date)
    # keeps/creates an incompatible combination -> must be rejected since
    # `rank` is part of this PATCH.
    with pytest.raises(SoldierValidationError, match="rank_track_incompatible"):
        update_soldier_profile(
            admin_session, soldier=soldier,
            fields={"rank": "רסן"}, actor_id=None,
        )


def test_soft_delete_cancels_pending_exemption_constraint_and_swap_requests(admin_session):
    from decimal import Decimal

    from app.db.models import (
        DutyLocation, DutyType, ExemptionRequest, ExemptionType,
        PersonalConstraint, SwapCandidate, SwapRequest,
    )
    from app.services import assignments as assignments_svc
    from app.services.soldiers import soft_delete
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7930002")
    covering = create_soldier(admin_session, personal_number="7930004")

    et = ExemptionType(name="soft_delete_test_exemption_type")
    admin_session.add(et)
    admin_session.flush()
    er = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id, start_date=date(2026, 8, 1),
        end_date=None, status="pending_commander",
    )
    admin_session.add(er)

    pc = PersonalConstraint(
        soldier_id=soldier.id, start_date=date(2026, 8, 1), end_date=date(2026, 8, 2),
        reason="soft_delete_test_constraint", status="pending_commander",
    )
    admin_session.add(pc)

    dt = DutyType(name="dt_soft_delete_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_soft_delete_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    assignment = assignments_svc.create_assignment(
        admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 2),
    )
    admin_session.flush()
    # Open swap request with a live candidate — the current equivalent of the
    # old "pending_approval" status (which no longer exists on SwapRequest).
    sr = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=date(2026, 8, 1),
        requesting_soldier_id=soldier.id, status="open",
    )
    admin_session.add(sr)
    admin_session.flush()
    candidate = SwapCandidate(
        swap_request_id=sr.id, soldier_id=covering.id, source="invited", status="pending",
    )
    admin_session.add(candidate)
    admin_session.commit()

    soft_delete(admin_session, soldier=soldier, actor_id=None)
    admin_session.commit()
    admin_session.refresh(er)
    admin_session.refresh(pc)
    admin_session.refresh(sr)
    admin_session.refresh(candidate)
    assert er.status == "cancelled"
    assert pc.status == "cancelled"
    assert sr.status == "cancelled"
    assert candidate.status == "cancelled"


def test_update_soldier_profile_manual_next_rank_date_sets_overridden(admin_session):
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920030")
    soldier.rank = "טוראי"
    admin_session.commit()

    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"next_rank_date": date(2030, 1, 1)}, actor_id=None,
    )
    assert soldier.next_rank_date == date(2030, 1, 1)
    assert soldier.next_rank_date_overridden is True


def test_clearing_next_rank_date_audits_resulting_automatic_state(admin_session):
    from app.db.models import AuditLog
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920033")
    soldier.rank = "סמר"
    soldier.enlistment_date = date(2021, 1, 15)
    admin_session.commit()
    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"next_rank_date": date(2030, 1, 1)}, actor_id=None,
    )
    admin_session.commit()

    update_soldier_profile(
        admin_session, soldier=soldier, fields={"next_rank_date": None}, actor_id=None,
    )
    admin_session.flush()

    audit = next(
        entry for entry in admin_session.query(AuditLog).filter_by(
            action="soldier.profile.update", entity_id=soldier.id,
        ).all()
        if entry.after.get("next_rank_date_overridden") is False
    )
    assert audit.after == {
        "next_rank_date": "2025-09-15",
        "next_rank_date_overridden": False,
    }


def test_update_soldier_profile_rank_change_with_explicit_date_updates_initial_anchor(admin_session):
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920032")
    soldier.rank = "טוראי"
    soldier.enlistment_date = date(2021, 1, 15)
    soldier.current_rank_since = date(2025, 1, 1)
    admin_session.commit()

    update_soldier_profile(
        admin_session,
        soldier=soldier,
        fields={"rank": "סמר", "next_rank_date": date(2030, 1, 1)},
        actor_id=None,
    )

    assert soldier.current_rank_since == date(2021, 1, 15)
    assert soldier.next_rank_date == date(2030, 1, 1)
    assert soldier.next_rank_date_overridden is True


def test_update_soldier_profile_rank_change_without_explicit_date_auto_computes(admin_session):
    from dateutil.relativedelta import relativedelta

    from app.services.rank_advancement import upsert_interval
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    upsert_interval(admin_session, track="enlisted", rank="רבט", months_to_next=8, advance_on_career_entry=False, actor_id=None)
    soldier = create_soldier(admin_session, personal_number="7920031")
    soldier.rank = "טוראי"
    admin_session.commit()

    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"rank": "רבט"}, actor_id=None,
    )
    assert soldier.current_rank_since == date.today()
    assert soldier.next_rank_date == date.today() + relativedelta(months=8)
    assert soldier.next_rank_date_overridden is False


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


def test_update_soldier_profile_unchanged_rank_does_not_reset_schedule(admin_session):
    """Finding 1: a PATCH that merely re-sends the soldier's current rank/track
    (e.g. because the frontend always includes them when the actor is
    authorized) must not be treated as a rank change — it must not re-anchor
    a worker-promoted soldier's schedule back to enlistment."""
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920034")
    soldier.enlistment_date = date(2021, 1, 15)
    soldier.rank = "רבט"
    soldier.rank_track = "enlisted"
    soldier.current_rank_since = date(2026, 3, 1)
    soldier.next_rank_date = date(2027, 2, 1)
    soldier.next_rank_date_overridden = False
    admin_session.commit()

    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"rank": "רבט", "rank_track": "enlisted", "phone": "0501234567"},
        actor_id=None,
    )

    assert soldier.current_rank_since == date(2026, 3, 1)
    assert soldier.next_rank_date == date(2027, 2, 1)
    assert soldier.phone == "0501234567"


def test_update_soldier_profile_enlistment_date_alone_reanchors_non_overridden_schedule(admin_session):
    """Finding 2: correcting enlistment_date alone (no rank/track change) must
    re-anchor current_rank_since and recompute next_rank_date, when the
    soldier's schedule isn't manually overridden — otherwise
    current_rank_since keeps pointing at the old (wrong) enlistment date and
    the soldier is misclassified as system-promoted."""
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920035")
    soldier.rank = "סמר"
    soldier.enlistment_date = date(2021, 1, 15)
    soldier.current_rank_since = date(2021, 1, 15)
    soldier.next_rank_date = date(2025, 9, 15)
    soldier.next_rank_date_overridden = False
    admin_session.commit()

    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"enlistment_date": date(2021, 2, 15)},
        actor_id=None,
    )

    assert soldier.current_rank_since == date(2021, 2, 15)
    assert soldier.next_rank_date == date(2025, 10, 15)
    assert soldier.next_rank_date_overridden is False


def test_update_soldier_profile_enlistment_date_does_not_touch_overridden_schedule(admin_session):
    """When next_rank_date_overridden is True, correcting enlistment_date must
    not silently discard the manual override."""
    from app.services.soldiers import update_soldier_profile
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920036")
    soldier.rank = "סמר"
    soldier.enlistment_date = date(2021, 1, 15)
    soldier.current_rank_since = date(2021, 1, 15)
    soldier.next_rank_date = date(2030, 1, 1)
    soldier.next_rank_date_overridden = True
    admin_session.commit()

    update_soldier_profile(
        admin_session, soldier=soldier,
        fields={"enlistment_date": date(2021, 2, 15)},
        actor_id=None,
    )

    assert soldier.next_rank_date == date(2030, 1, 1)
    assert soldier.next_rank_date_overridden is True


def test_approve_field_update_writes_last_mitvahim_date(admin_session):
    from app.services.soldiers import approve_field_update, submit_field_update
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="7920006")
    update = submit_field_update(
        admin_session,
        soldier_id=soldier.id,
        field_name="last_mitvahim_date",
        new_value="2026-08-15",
        actor_id=soldier.id,
    )

    approve_field_update(admin_session, update=update, actor_id=soldier.id)

    assert soldier.last_mitvahim_date == date(2026, 8, 15)
