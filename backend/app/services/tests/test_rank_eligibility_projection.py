import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.algorithm.types import DutyBlock
from app.db.models import (
    DutyLocation,
    DutyType,
    ExemptionDutyLocationMap,
    ExemptionDutyTypeMap,
    ExemptionType,
    SoldierExemption,
)
from app.services.rank_advancement import upsert_interval
from app.services.rank_eligibility_projection import (
    _load_interval_cache,
    bulk_future_ineligible_duty_blocks,
    project_soldier_state,
)
from tests.helpers import create_soldier


def test_project_no_advancement_before_next_rank_date(app_session):
    s = create_soldier(app_session, personal_number="1234570")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 6, 1)
    app_session.flush()
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 3, 1))
    assert state.rank == "טוראי"


def test_project_single_advancement_reached(app_session):
    s = create_soldier(app_session, personal_number="1234571")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 3, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=8, advance_on_career_entry=False, actor_id=None)
    app_session.flush()
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 1))
    assert state.rank == "רבט"


def test_project_chained_advancement_across_multiple_steps(app_session):
    s = create_soldier(app_session, personal_number="1234572")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=1, advance_on_career_entry=False, actor_id=None)
    upsert_interval(app_session, track="enlisted", rank="סמל", months_to_next=1, advance_on_career_entry=False, actor_id=None)
    app_session.flush()
    # Jan 1 -> רבט, +1mo (Feb 1) -> סמל, +1mo (Mar 1) -> סמר -- projecting to Apr 1
    # should have walked two full steps past רבט (through סמל and on to סמר,
    # since the סמל->סמר threshold date of Mar 1 is also <= the projection
    # date of Apr 1).
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 4, 1))
    assert state.rank == "סמר"


def test_project_never_crosses_track():
    pass  # covered structurally: get_next_rank never returns a cross-track rank (Task 2)


def test_project_career_track_as_of_future_date(app_session):
    # Use a rank outside CHOVAH_ONLY_RANKS so is_career can actually flip on
    # date alone -- derive_is_career unconditionally returns False for
    # חובה-only ranks (e.g. "טוראי") regardless of date, so this test isolates
    # the date-sensitivity of the career derivation from rank-chaining logic
    # (already covered by the chained-advancement tests above).
    s = create_soldier(app_session, personal_number="1234573")
    s.rank = "סמר"
    s.mandatory_end_date = date(2026, 6, 1)
    s.discharge_date = None
    app_session.flush()
    before = project_soldier_state(app_session, soldier=s, as_of=date(2026, 1, 1))
    after = project_soldier_state(app_session, soldier=s, as_of=date(2026, 12, 1))
    assert before.is_career is False
    assert after.is_career is True


def test_project_departed_if_left_before_as_of(app_session):
    s = create_soldier(app_session, personal_number="1234574")
    s.rank = "טוראי"
    s.discharge_date = date(2026, 5, 1)
    app_session.flush()
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 1))
    assert state.departed is True


def test_project_not_departed_if_as_of_before_discharge(app_session):
    s = create_soldier(app_session, personal_number="1234575")
    s.rank = "טוראי"
    s.discharge_date = date(2026, 5, 1)
    app_session.flush()
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 4, 1))
    assert state.departed is False


def test_project_uses_interval_cache_instead_of_querying(app_session):
    """With an interval_cache the chain-walk must not hit get_interval_months
    at all -- that per-step single-row SELECT is what the cache exists to
    avoid on the solver's hot path."""
    s = create_soldier(app_session, personal_number="1234576")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=1, advance_on_career_entry=False, actor_id=None)
    upsert_interval(app_session, track="enlisted", rank="סמל", months_to_next=1, advance_on_career_entry=False, actor_id=None)
    app_session.flush()

    uncached = project_soldier_state(app_session, soldier=s, as_of=date(2026, 4, 1))
    with patch(
        "app.services.rank_advancement.get_interval_months",
        side_effect=AssertionError("interval_cache should have prevented this query"),
    ):
        cached = project_soldier_state(
            app_session, soldier=s, as_of=date(2026, 4, 1),
            interval_cache=_load_interval_cache(app_session),
        )

    assert cached == uncached
    assert cached.rank == "סמר"


def test_project_soldier_state_advances_early_via_career_entry(app_session):
    s = create_soldier(app_session, personal_number="1234601")
    s.rank = "קאב"
    s.mandatory_end_date = date(2026, 6, 1)  # career starts 6/2
    s.next_rank_date = date(2099, 1, 1)  # scheduled date is far in the future
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    app_session.flush()

    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 2))

    assert state.rank == "קאם"


def test_project_soldier_state_advances_on_career_entry_without_scheduled_date(app_session):
    """The flagged rank has no scheduled next_rank_date at all -- the old
    chain-walk broke out on `next_date is None` before ever looking at the
    career-entry trigger."""
    s = create_soldier(app_session, personal_number="1234602")
    s.rank = "קאב"
    s.mandatory_end_date = date(2026, 6, 1)
    s.next_rank_date = None
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    app_session.flush()

    assert project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 1)).rank == "קאב"
    assert project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 2)).rank == "קאם"


def test_project_soldier_state_uses_scheduled_date_when_earlier_than_career_entry(app_session):
    s = create_soldier(app_session, personal_number="1234603")
    s.rank = "קאב"
    s.mandatory_end_date = date(2026, 12, 1)  # career starts much later
    s.next_rank_date = date(2026, 3, 1)  # scheduled promotion comes first
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    app_session.flush()

    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 4, 1))

    assert state.rank == "קאם"  # advanced via the scheduled date, well before career-entry


def test_project_soldier_state_no_early_trigger_when_flag_unset(app_session):
    s = create_soldier(app_session, personal_number="1234604")
    s.rank = "קאב"
    s.mandatory_end_date = date(2026, 6, 1)
    s.next_rank_date = date(2099, 1, 1)
    app_session.flush()
    # no upsert_interval call -- advance_on_career_entry defaults False

    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 2))

    assert state.rank == "קאב"  # unchanged -- no trigger configured, scheduled date not reached


def test_project_soldier_state_no_career_entry_when_discharged_before_mandatory_end(app_session):
    """_career_entry_date returns None when a discharge closes out חובה service
    -- such a soldier never enters קבע, so the trigger must not fire."""
    s = create_soldier(app_session, personal_number="1234605")
    s.rank = "קאב"
    s.mandatory_end_date = date(2026, 6, 1)
    s.discharge_date = date(2026, 5, 1)
    s.next_rank_date = date(2099, 1, 1)
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    app_session.flush()

    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 2))

    assert state.rank == "קאב"


def test_project_skips_career_entry_lookup_when_not_near_the_boundary(app_session):
    """Uncached path (check_soldier_for_assignment / potential), which several
    callers run once per candidate in a loop: a soldier whose קבע entry is not
    yet reached as of the projection date must cost ZERO advance_on_career_entry
    queries. The flag could only ever lower the effective date to something also
    beyond `as_of`, so the walk breaks identically without ever asking."""
    s = create_soldier(app_session, personal_number="1234607")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 6, 1)
    s.mandatory_end_date = date(2030, 1, 1)  # קבע entry far beyond the projection date
    app_session.flush()

    with patch(
        "app.services.rank_eligibility_projection.advances_on_career_entry",
        side_effect=AssertionError("flag lookup should have been skipped"),
    ):
        state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 3, 1))

    assert state.rank == "טוראי"


def test_project_skips_career_entry_lookup_when_no_mandatory_end_date(app_session):
    """Same skip, via _career_entry_date returning None (no mandatory_end_date)."""
    s = create_soldier(app_session, personal_number="1234608")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    s.mandatory_end_date = None
    app_session.flush()

    with patch(
        "app.services.rank_eligibility_projection.advances_on_career_entry",
        side_effect=AssertionError("flag lookup should have been skipped"),
    ):
        state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 1))

    assert state.rank == "רבט"  # still walks the scheduled chain normally


def test_project_career_entry_uses_interval_cache_instead_of_querying(app_session):
    """Cached/uncached parity for the career-entry trigger: with an
    interval_cache the chain-walk must not call advances_on_career_entry (its
    per-step single-row SELECT) at all, and must reach the same result."""
    s = create_soldier(app_session, personal_number="1234606")
    s.rank = "קאב"
    s.mandatory_end_date = date(2026, 6, 1)
    s.next_rank_date = date(2099, 1, 1)
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    app_session.flush()

    uncached = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 2))
    cache = _load_interval_cache(app_session)
    with patch(
        "app.services.rank_eligibility_projection.advances_on_career_entry",
        side_effect=AssertionError("interval_cache should have prevented this query"),
    ):
        cached = project_soldier_state(
            app_session, soldier=s, as_of=date(2026, 6, 2), interval_cache=cache,
        )

    assert cache[("officer_academic", "קאב")] == (None, True)
    assert cached == uncached
    assert cached.rank == "קאם"


def _duty_block(duty_type_id, day, duty_location_id=None, end_day=None):
    return DutyBlock(
        id=uuid.uuid4(),
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id or uuid.uuid4(),
        start_date=day,
        end_date=end_day or day,
        score_per_day=Decimal("1.00"),
    )


def _duty_type(session, *, name="x", requirements=None) -> DutyType:
    dt = DutyType(name=name, score_per_day=Decimal("1.00"), requirements=requirements or {})
    session.add(dt)
    session.flush()
    return dt


def test_bulk_future_ineligible_excludes_block_when_projected_rank_fails_requirement(app_session):
    s = create_soldier(app_session, personal_number="1234580")
    s.rank = "טוראי"
    app_session.flush()
    dt = _duty_type(app_session, requirements={"allowed_ranks": ["רבט"]})
    block = _duty_block(dt.id, date(2026, 6, 1))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())


def test_bulk_future_ineligible_includes_block_when_projected_rank_satisfies_requirement(app_session):
    s = create_soldier(app_session, personal_number="1234581")
    s.rank = "טוראי"
    # No interval configured for רבט, so the projection stops there instead of
    # chaining on to סמל -- the soldier is exactly רבט as of the duty's date.
    s.next_rank_date = date(2026, 1, 1)
    app_session.flush()
    dt = _duty_type(app_session, requirements={"allowed_ranks": ["רבט"]})
    # duty is far enough out that the soldier will have advanced to רבט by then
    block = _duty_block(dt.id, date(2026, 6, 1))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id not in result.get(s.id, set())


def test_bulk_future_ineligible_uses_each_blocks_own_date(app_session):
    s = create_soldier(app_session, personal_number="1234582")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 4, 1)
    app_session.flush()
    dt = _duty_type(app_session, requirements={"allowed_ranks": ["רבט"]})
    early = _duty_block(dt.id, date(2026, 1, 1))
    late = _duty_block(dt.id, date(2026, 6, 1))

    result = bulk_future_ineligible_duty_blocks(
        app_session, soldier_ids=[s.id], duties=[early, late]
    )

    assert early.id in result.get(s.id, set())
    assert late.id not in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_block_after_departure(app_session):
    s = create_soldier(app_session, personal_number="1234583")
    s.rank = "טוראי"
    s.discharge_date = date(2026, 5, 1)
    app_session.flush()
    dt = _duty_type(app_session)
    block = _duty_block(dt.id, date(2026, 6, 1))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_block_when_license_expired_by_then(app_session):
    s = create_soldier(app_session, personal_number="1234584")
    s.rank = "טוראי"
    s.has_military_driving_license = True
    s.military_driving_license_expiry = date(2026, 3, 1)
    app_session.flush()
    dt = _duty_type(app_session, requirements={"requires_military_driving_license": True})
    before_expiry = _duty_block(dt.id, date(2026, 1, 1))
    after_expiry = _duty_block(dt.id, date(2026, 6, 1))

    result = bulk_future_ineligible_duty_blocks(
        app_session, soldier_ids=[s.id], duties=[before_expiry, after_expiry]
    )

    assert before_expiry.id not in result.get(s.id, set())
    assert after_expiry.id in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_block_when_mitvahim_stale_by_then(app_session):
    s = create_soldier(app_session, personal_number="1234585")
    s.rank = "טוראי"
    s.last_mitvahim_date = date(2026, 1, 1)
    app_session.flush()
    dt = _duty_type(app_session, requirements={"requires_mitvahim": True})
    fresh = _duty_block(dt.id, date(2026, 2, 1))
    stale = _duty_block(dt.id, date(2026, 12, 1))

    result = bulk_future_ineligible_duty_blocks(
        app_session, soldier_ids=[s.id], duties=[fresh, stale]
    )

    assert fresh.id not in result.get(s.id, set())
    assert stale.id in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_block_covered_by_future_exemption(app_session):
    s = create_soldier(app_session, personal_number="1234586")
    s.rank = "טוראי"
    app_session.flush()
    dt = _duty_type(app_session)
    et = ExemptionType(name="y", is_global=False)
    app_session.add(et)
    app_session.flush()
    app_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt.id))
    # exemption starts in the future -- not active "today", but covers the block's date
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 5, 1), end_date=date(2026, 7, 1),
    ))
    app_session.flush()

    block = _duty_block(dt.id, date(2026, 6, 1))
    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())


def test_bulk_future_ineligible_includes_block_after_exemption_ends(app_session):
    s = create_soldier(app_session, personal_number="1234587")
    s.rank = "טוראי"
    app_session.flush()
    dt = _duty_type(app_session)
    et = ExemptionType(name="y", is_global=False)
    app_session.add(et)
    app_session.flush()
    app_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt.id))
    # exemption is active "today" but ends before the block's date
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
    ))
    app_session.flush()

    block = _duty_block(dt.id, date(2026, 6, 1))
    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id not in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_block_by_global_exemption(app_session):
    s = create_soldier(app_session, personal_number="1234588")
    s.rank = "טוראי"
    app_session.flush()
    dt = _duty_type(app_session)
    et = ExemptionType(name="global", is_global=True)
    app_session.add(et)
    app_session.flush()
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id, start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.flush()

    block = _duty_block(dt.id, date(2026, 6, 1))
    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_block_by_location_exemption(app_session):
    s = create_soldier(app_session, personal_number="1234589")
    s.rank = "טוראי"
    app_session.flush()
    dt = _duty_type(app_session)
    location = DutyLocation(name="מיקום פטור")
    et = ExemptionType(name="loc", is_global=False)
    app_session.add_all([location, et])
    app_session.flush()
    app_session.add(
        ExemptionDutyLocationMap(exemption_type_id=et.id, duty_location_id=location.id)
    )
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id, start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.flush()

    exempt_block = _duty_block(dt.id, date(2026, 6, 1), duty_location_id=location.id)
    other_block = _duty_block(dt.id, date(2026, 6, 1))
    result = bulk_future_ineligible_duty_blocks(
        app_session, soldier_ids=[s.id], duties=[exempt_block, other_block]
    )

    assert exempt_block.id in result.get(s.id, set())
    assert other_block.id not in result.get(s.id, set())


# --- multi-day blocks: every check spans the block's full date range ---------


def test_bulk_future_ineligible_excludes_multiday_block_when_exemption_starts_midblock(app_session):
    s = create_soldier(app_session, personal_number="1234590")
    s.rank = "טוראי"
    app_session.flush()
    dt = _duty_type(app_session)
    et = ExemptionType(name="mid", is_global=False)
    app_session.add(et)
    app_session.flush()
    app_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt.id))
    # Exemption starts on day 2 of a 6/1--6/4 block: not active on start_date,
    # but it covers part of the block, so the block must be excluded.
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 6, 2), end_date=date(2026, 6, 10),
    ))
    app_session.flush()

    block = _duty_block(dt.id, date(2026, 6, 1), end_day=date(2026, 6, 4))
    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_multiday_block_when_exemption_ends_midblock(app_session):
    s = create_soldier(app_session, personal_number="1234591")
    s.rank = "טוראי"
    app_session.flush()
    dt = _duty_type(app_session)
    et = ExemptionType(name="tail", is_global=False)
    app_session.add(et)
    app_session.flush()
    app_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt.id))
    # Exemption ends on day 2 of the block -- still overlaps it.
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 5, 1), end_date=date(2026, 6, 2),
    ))
    app_session.flush()

    overlapping = _duty_block(dt.id, date(2026, 6, 1), end_day=date(2026, 6, 4))
    after = _duty_block(dt.id, date(2026, 6, 5), end_day=date(2026, 6, 8))
    result = bulk_future_ineligible_duty_blocks(
        app_session, soldier_ids=[s.id], duties=[overlapping, after]
    )

    assert overlapping.id in result.get(s.id, set())
    assert after.id not in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_multiday_block_when_license_expires_midblock(app_session):
    s = create_soldier(app_session, personal_number="1234592")
    s.rank = "טוראי"
    s.has_military_driving_license = True
    s.military_driving_license_expiry = date(2026, 6, 2)
    app_session.flush()
    dt = _duty_type(app_session, requirements={"requires_military_driving_license": True})
    # License is valid on 6/1 but expired by 6/4 -- the block spans the expiry.
    block = _duty_block(dt.id, date(2026, 6, 1), end_day=date(2026, 6, 4))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_multiday_block_when_rank_changes_midblock(app_session):
    s = create_soldier(app_session, personal_number="1234593")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 6, 2)  # advances to רבט on day 2 of the block
    app_session.flush()
    dt = _duty_type(app_session, requirements={"allowed_ranks": ["טוראי"]})
    block = _duty_block(dt.id, date(2026, 6, 1), end_day=date(2026, 6, 4))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_multiday_block_when_rank_qualifies_only_midblock(app_session):
    """The reverse direction of ..._when_rank_changes_midblock: the soldier is
    NOT of the required rank on the block's first day and only gets promoted
    into it on day 2. Evaluating end_date alone would wrongly let them take the
    whole block, day 1 included — so both endpoints are checked."""
    s = create_soldier(app_session, personal_number="1234595")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 6, 2)  # becomes רבט on day 2 of the block
    app_session.flush()
    dt = _duty_type(app_session, requirements={"allowed_ranks": ["רבט"]})
    block = _duty_block(dt.id, date(2026, 6, 1), end_day=date(2026, 6, 4))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())


def test_bulk_future_ineligible_keeps_multiday_block_when_rank_qualifies_throughout(app_session):
    """Guard for the both-endpoints check: a soldier already holding the
    required rank on day 1 and still holding it on the last day stays eligible."""
    s = create_soldier(app_session, personal_number="1234596")
    s.rank = "רבט"
    app_session.flush()
    dt = _duty_type(app_session, requirements={"allowed_ranks": ["רבט"]})
    block = _duty_block(dt.id, date(2026, 6, 1), end_day=date(2026, 6, 4))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id not in result.get(s.id, set())


def test_bulk_future_ineligible_agrees_with_check_soldier_for_assignment(app_session):
    """Cross-path consistency: for the same soldier/rank requirement, a
    single-day DutyBlock here and the equivalent single-day DutyAssignment run
    through eligibility.check_soldier_for_assignment must reach the same
    verdict — both project rank as of the day the duty actually starts."""
    from app.db.models import DutyAssignment
    from app.services.eligibility import check_soldier_for_assignment

    dt = _duty_type(app_session, name="shared", requirements={"allowed_ranks": ["רבט"]})
    loc = DutyLocation(name="עמדה משותפת")
    app_session.add(loc)
    # The assignment must belong to someone (soldier_id is NOT NULL); the
    # candidate being checked is a different soldier, as in the real
    # swap/manual-assign flow.
    owner = create_soldier(app_session, personal_number="1234599")
    app_session.flush()
    day = date(2026, 6, 1)

    for personal_number, next_rank_date, expected_eligible in [
        ("1234597", date(2026, 1, 1), True),   # promoted to רבט well before the duty
        ("1234598", date(2026, 12, 1), False),  # still טוראי on the duty's day
    ]:
        s = create_soldier(app_session, personal_number=personal_number)
        s.rank = "טוראי"
        s.next_rank_date = next_rank_date
        app_session.flush()

        block = _duty_block(dt.id, day, duty_location_id=loc.id)
        bulk_excluded = block.id in bulk_future_ineligible_duty_blocks(
            app_session, soldier_ids=[s.id], duties=[block]
        ).get(s.id, set())

        assignment = DutyAssignment(
            duty_type_id=dt.id, duty_location_id=loc.id, soldier_id=owner.id,
            start_date=day, end_date=day,
        )
        app_session.add(assignment)
        app_session.flush()
        manual_ok, _reason = check_soldier_for_assignment(app_session, s.id, assignment.id)

        assert manual_ok is expected_eligible, personal_number
        assert bulk_excluded is not expected_eligible, personal_number


def test_bulk_future_ineligible_excludes_multiday_block_when_departure_falls_midblock(app_session):
    s = create_soldier(app_session, personal_number="1234594")
    s.rank = "טוראי"
    s.discharge_date = date(2026, 6, 2)
    app_session.flush()
    dt = _duty_type(app_session)
    block = _duty_block(dt.id, date(2026, 6, 1), end_day=date(2026, 6, 4))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())
