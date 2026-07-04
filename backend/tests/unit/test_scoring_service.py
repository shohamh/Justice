from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models import DutyLocation, DutyType, ExemptionType, SoldierExemption
from app.services.adjustments import create_adjustment
from app.services.assignments import cancel_assignment, create_assignment, set_day_override
from app.services.duty_config import map_exemption_to_duty_type
from app.services.scoring import (
    active_days,
    cumulative_score,
    effective_duty_days,
    effective_duty_spans,
    normalised_score,
    soldier_score_breakdown,
    transparency_rows,
)
from tests.helpers import create_soldier


def _dt(session, name, score):
    dt = DutyType(name=name, score_per_day=Decimal(score))
    session.add(dt)
    session.flush()
    return dt


def _loc(session, name):
    loc = DutyLocation(name=name)
    session.add(loc)
    session.flush()
    return loc


def test_effective_days_basic_block(admin_session):
    s = create_soldier(admin_session, personal_number="8400001")
    dt = _dt(admin_session, "שמירה-sc1", "1.00")
    loc = _loc(admin_session, "מוצב-sc1")
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 4),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    days = [d for d in effective_duty_days(admin_session) if d[1] == s.id]
    assert len(days) == 3


def test_effective_duty_days_spreads_score_days_evenly_across_touched_days(admin_session):
    from app.db.models import DutyAssignment

    s = create_soldier(admin_session, personal_number="8400201")
    dt = _dt(admin_session, "dt_scoring_spread", "10.00")
    loc = _loc(admin_session, "loc_scoring_spread")

    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 9),
        start_time="14:00", end_time="14:00", status="published",
    )
    admin_session.add(a)
    admin_session.flush()

    rows = [r for r in effective_duty_days(admin_session) if r[1] == s.id]
    assert len(rows) == 8  # calendar_days_touched unchanged
    total_score = sum(dt.score_per_day * mult for _day, _eff, _dtid, mult in rows)
    assert total_score == Decimal("70")  # 10 * score_days(7), not 10 * 8 = 80


def test_effective_duty_days_zero_day_assignment_does_not_crash(admin_session):
    """Zero-duration assignments (start == end) are rejected by the service but may exist
    as legacy DB rows. Scoring must not raise ZeroDivisionError and must return no rows."""
    from app.db.models import DutyAssignment
    s = create_soldier(admin_session, personal_number="8400301")
    dt = _dt(admin_session, "dt_zero_day", "5.00")
    loc = _loc(admin_session, "loc_zero_day")
    # Insert directly, bypassing service validation, to simulate legacy bad data.
    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 1), status="published",
    )
    admin_session.add(a)
    admin_session.flush()
    rows = [r for r in effective_duty_days(admin_session) if r[1] == s.id]
    assert rows == []


def test_cumulative_with_override_and_adjustment(admin_session):
    s = create_soldier(admin_session, personal_number="8400002")
    repl = create_soldier(admin_session, personal_number="8400003")
    dt = _dt(admin_session, "שמירה-sc2", "2.00")
    loc = _loc(admin_session, "מוצב-sc2")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 4),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 9, 2),
        effective_soldier_id=repl.id,
        reason="replacement",
        actor_id=None,
    )
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 9, 3),
        effective_soldier_id=None,
        reason="cancelled",
        actor_id=None,
    )
    create_adjustment(
        admin_session, soldier_id=s.id, delta=Decimal("5.00"), reason="פיצוי", actor_id=None
    )
    admin_session.flush()
    assert cumulative_score(admin_session, soldier_id=s.id) == Decimal("7.00")
    assert cumulative_score(admin_session, soldier_id=repl.id) == Decimal("2.00")


def test_cancelled_assignment_excluded(admin_session):
    s = create_soldier(admin_session, personal_number="8400004")
    dt = _dt(admin_session, "שמירה-sc3", "3.00")
    loc = _loc(admin_session, "מוצב-sc3")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    cancel_assignment(admin_session, assignment=a, reason="בוטל", actor_id=None)
    admin_session.flush()
    assert cumulative_score(admin_session, soldier_id=s.id) == Decimal("0")


def test_active_days_subtracts_full_coverage_exemption(admin_session):
    s = create_soldier(admin_session, personal_number="8500001")
    s.enrolled_at = date.today() - timedelta(days=10)
    admin_session.flush()
    _dt(admin_session, "שמירה-ad1", "1.00")
    et = ExemptionType(name="פטור-מלא-ad1")
    admin_session.add(et)
    admin_session.flush()
    # Full coverage = exemption maps to EVERY currently-active duty type. Other tests in the
    # shared session commit duty types too, so map to all active ones (not just this test's).
    active_ids = (
        admin_session.execute(select(DutyType.id).where(DutyType.active.is_(True))).scalars().all()
    )
    for dtid in active_ids:
        map_exemption_to_duty_type(
            admin_session, exemption_type_id=et.id, duty_type_id=dtid, actor_id=None
        )
    admin_session.add(
        SoldierExemption(
            soldier_id=s.id,
            exemption_type_id=et.id,
            start_date=date.today() - timedelta(days=4),
            end_date=date.today(),
        )
    )
    admin_session.flush()
    assert active_days(admin_session, soldier=s) == 5


def test_active_days_floor_is_one(admin_session):
    s = create_soldier(admin_session, personal_number="8500002")
    s.enrolled_at = date.today()
    admin_session.flush()
    assert active_days(admin_session, soldier=s) == 1


def test_partial_coverage_does_not_reduce_active_days(admin_session):
    s = create_soldier(admin_session, personal_number="8500003")
    s.enrolled_at = date.today() - timedelta(days=10)
    admin_session.flush()
    d1 = _dt(admin_session, "שמירה-ad3a", "1.00")
    _dt(admin_session, "ניקיון-ad3b", "1.00")
    et = ExemptionType(name="פטור-חלקי-ad3")
    admin_session.add(et)
    admin_session.flush()
    map_exemption_to_duty_type(
        admin_session, exemption_type_id=et.id, duty_type_id=d1.id, actor_id=None
    )
    admin_session.add(
        SoldierExemption(
            soldier_id=s.id,
            exemption_type_id=et.id,
            start_date=date.today() - timedelta(days=4),
            end_date=date.today(),
        )
    )
    admin_session.flush()
    assert active_days(admin_session, soldier=s) == 10


def test_normalised_and_transparency(admin_session):
    s = create_soldier(admin_session, personal_number="8500004")
    s.enrolled_at = date.today() - timedelta(days=10)
    admin_session.flush()
    dt = _dt(admin_session, "שמירה-tr", "2.00")
    loc = _loc(admin_session, "מוצב-tr")
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=3),
        end_date=date.today() - timedelta(days=1),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    assert normalised_score(admin_session, soldier=s) == Decimal("4.00") / Decimal("10")
    rows = transparency_rows(admin_session, viewer=s)["rows"]
    mine = next(r for r in rows if r["soldier_id"] == s.id)
    assert mine["cumulative_score"] == Decimal("4.00")
    assert mine["active_days"] == 10
    norms = [r["normalised_score"] for r in rows]
    assert norms == sorted(norms, reverse=True)


def test_transparency_exemption_in_scope_shows_real_label(admin_session):
    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-exempt-scope")
    dm = create_soldier(
        admin_session, personal_number="8500010", role="duty_manager", hierarchy_node_id=node.id
    )
    s = create_soldier(admin_session, personal_number="8500011", hierarchy_node_id=node.id)
    et = ExemptionType(name="מגבלה רפואית", is_global=False)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(
            soldier_id=s.id,
            exemption_type_id=et.id,
            start_date=date.today() - timedelta(days=1),
            end_date=date.today() + timedelta(days=30),
        )
    )
    admin_session.commit()

    result = transparency_rows(admin_session, viewer=dm)
    row = next(r for r in result["rows"] if r["soldier_id"] == s.id)
    assert row["exemptions_visible"] is True
    assert row["exemptions_display"].startswith("מגבלה רפואית (חלקי, עד ")
    assert row["has_global_exemption"] is False
    assert row["has_partial_exemption"] is True
    assert row["has_temporary_exemption"] is True


def test_transparency_exemption_out_of_scope_is_redacted(admin_session):
    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-exempt-outscope")
    other_node = create_node(admin_session, level="division", name="div-exempt-other")
    viewer_dm = create_soldier(
        admin_session, personal_number="8500012", role="duty_manager", hierarchy_node_id=other_node.id
    )
    s = create_soldier(admin_session, personal_number="8500013", hierarchy_node_id=node.id)
    et = ExemptionType(name="שחרור", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(soldier_id=s.id, exemption_type_id=et.id, start_date=date.today())
    )
    admin_session.commit()

    result = transparency_rows(admin_session, viewer=viewer_dm)
    row = next(r for r in result["rows"] if r["soldier_id"] == s.id)
    assert row["exemptions_visible"] is False
    assert row["exemptions_display"] == "חסוי"
    # aggregate gate passes (viewer holds a scope somewhere), so booleans are still present
    assert row["has_global_exemption"] is True


def test_transparency_aggregate_flags_absent_for_plain_soldier_viewer(admin_session):
    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-exempt-plain")
    plain_viewer = create_soldier(admin_session, personal_number="8500014", role="soldier")
    s = create_soldier(admin_session, personal_number="8500015", hierarchy_node_id=node.id)
    et = ExemptionType(name="שחרור", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(soldier_id=s.id, exemption_type_id=et.id, start_date=date.today())
    )
    admin_session.commit()

    result = transparency_rows(admin_session, viewer=plain_viewer)
    assert result["can_see_exemption_aggregates"] is False
    row = next(r for r in result["rows"] if r["soldier_id"] == s.id)
    assert row["exemptions_display"] == "חסוי"
    assert row["has_global_exemption"] is None
    assert row["has_partial_exemption"] is None
    assert row["has_temporary_exemption"] is None


def test_breakdown(admin_session):
    s = create_soldier(admin_session, personal_number="8500005")
    dt = _dt(admin_session, "שמירה-bd", "1.50")
    loc = _loc(admin_session, "מוצב-bd")
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        notes=None,
        actor_id=None,
    )
    create_adjustment(
        admin_session, soldier_id=s.id, delta=Decimal("3.00"), reason="פיצוי", actor_id=None
    )
    admin_session.flush()
    bd = soldier_score_breakdown(admin_session, soldier_id=s.id)
    pt = next(pt for pt in bd["per_type"] if pt["duty_type_id"] == dt.id)
    assert pt["score"] == Decimal("3.00")
    assert pt["days"] == 2
    assert len(bd["adjustments"]) == 1


def test_effective_spans_split_on_override(admin_session):
    s = create_soldier(admin_session, personal_number="8600001")
    repl = create_soldier(admin_session, personal_number="8600002")
    dt = _dt(admin_session, "שמירה-sp1", "1.00")
    loc = _loc(admin_session, "מוצב-sp1")
    a = create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 6),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 12, 3),
        effective_soldier_id=repl.id,
        reason="replacement",
        actor_id=None,
    )
    set_day_override(
        admin_session,
        assignment=a,
        date=date(2026, 12, 5),
        effective_soldier_id=None,
        reason="cancelled",
        actor_id=None,
    )
    admin_session.flush()
    s_spans = effective_duty_spans(admin_session, soldier_ids={s.id})
    s_ranges = sorted(
        (sp["start_date"], sp["end_date"]) for sp in s_spans if sp["soldier_id"] == s.id
    )
    # s keeps days 1-2 and day 4 (day 3 reassigned, day 5 cancelled)
    assert s_ranges == [
        (date(2026, 12, 1), date(2026, 12, 3)),
        (date(2026, 12, 4), date(2026, 12, 5)),
    ]
    repl_spans = effective_duty_spans(admin_session, soldier_ids={repl.id})
    repl_ranges = [
        (sp["start_date"], sp["end_date"]) for sp in repl_spans if sp["soldier_id"] == repl.id
    ]
    assert repl_ranges == [(date(2026, 12, 3), date(2026, 12, 4))]


def test_effective_spans_no_override_is_single_block(admin_session):
    s = create_soldier(admin_session, personal_number="8600003")
    dt = _dt(admin_session, "שמירה-sp2", "1.00")
    loc = _loc(admin_session, "מוצב-sp2")
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 13),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    spans = [
        sp
        for sp in effective_duty_spans(admin_session, soldier_ids={s.id})
        if sp["soldier_id"] == s.id
    ]
    assert len(spans) == 1
    assert spans[0]["start_date"] == date(2026, 12, 10)
    assert spans[0]["end_date"] == date(2026, 12, 13)
    assert spans[0]["duty_location_id"] == loc.id
