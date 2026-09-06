from datetime import date, timedelta

from sqlalchemy import select

from app.db.models import DutyType, ExemptionType, SoldierExemption
from app.services.duty_config import map_exemption_to_duty_type
from app.services.scoring import _bulk_active_days, active_days, effective_active_start
from app.services.settings_loader import FAIRNESS_RESET_DATE_KEY, set_setting
from tests.helpers import create_soldier


def _set_reference_date(session, reference_date: date) -> None:
    set_setting(session, FAIRNESS_RESET_DATE_KEY, reference_date.isoformat(), actor_id=None)


def _full_coverage_exemption(session, *, soldier_id, start_date: date, end_date: date) -> None:
    duty_type = DutyType(name=f"active-days-duty-{soldier_id}", score_per_day=1)
    exemption_type = ExemptionType(name=f"active-days-exemption-{soldier_id}")
    session.add_all([duty_type, exemption_type])
    session.flush()
    for duty_type_id in session.execute(
        select(DutyType.id).where(DutyType.active.is_(True))
    ).scalars():
        map_exemption_to_duty_type(
            session,
            exemption_type_id=exemption_type.id,
            duty_type_id=duty_type_id,
            actor_id=None,
        )
    session.add(
        SoldierExemption(
            soldier_id=soldier_id,
            exemption_type_id=exemption_type.id,
            start_date=start_date,
            end_date=end_date,
        )
    )
    session.flush()


def test_effective_active_start_uses_reference_for_legacy_soldier():
    reference_date = date(2026, 8, 1)

    assert effective_active_start(reference_date, None) == reference_date


def test_effective_active_start_uses_later_unit_join_date():
    assert effective_active_start(date(2026, 8, 1), date(2026, 8, 15)) == date(2026, 8, 15)
    assert effective_active_start(date(2026, 8, 15), date(2026, 8, 1)) == date(2026, 8, 15)


def test_active_days_caps_end_at_earliest_discharge_or_left_date(admin_session):
    today = date.today()
    soldier = create_soldier(admin_session, personal_number="active-days-end-cap")
    _set_reference_date(admin_session, today - timedelta(days=20))
    soldier.discharge_date = today - timedelta(days=7)
    soldier.left_at = today - timedelta(days=10)
    admin_session.flush()

    assert active_days(admin_session, soldier=soldier) == 10


def test_active_days_stays_one_when_effective_start_is_after_end(admin_session):
    today = date.today()
    soldier = create_soldier(admin_session, personal_number="active-days-minimum")
    _set_reference_date(admin_session, today)
    soldier.left_at = today - timedelta(days=1)
    admin_session.flush()

    assert active_days(admin_session, soldier=soldier) == 1


def test_active_days_clips_full_coverage_exemptions_to_effective_window(admin_session):
    today = date.today()
    soldier = create_soldier(admin_session, personal_number="active-days-exemption")
    reference_date = today - timedelta(days=10)
    _set_reference_date(admin_session, reference_date)
    soldier.unit_join_date = today - timedelta(days=5)
    _full_coverage_exemption(
        admin_session,
        soldier_id=soldier.id,
        start_date=today - timedelta(days=8),
        end_date=today + timedelta(days=2),
    )

    assert active_days(admin_session, soldier=soldier) == 1


def test_bulk_active_days_matches_single_soldier_dynamic_fallback_without_setting(admin_session):
    """With no fairness.reset_date set and no published duty history, both the
    bulk and single-soldier paths fall back to the same dynamic reset date
    (see scoring._burden_share_reset_date) -- `unit_join_date` is what still
    differentiates soldiers in that case, since a bare reset date is shared by
    everyone."""
    today = date.today()
    earlier = create_soldier(admin_session, personal_number="active-days-bulk-earlier")
    later = create_soldier(admin_session, personal_number="active-days-bulk-later")
    earlier.unit_join_date = today - timedelta(days=10)
    later.unit_join_date = today - timedelta(days=3)
    admin_session.flush()

    assert _bulk_active_days(admin_session, [earlier, later]) == {
        earlier.id: active_days(admin_session, soldier=earlier),
        later.id: active_days(admin_session, soldier=later),
    }
