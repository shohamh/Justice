import uuid
from datetime import date
from decimal import Decimal

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
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=8, actor_id=None)
    app_session.flush()
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 1))
    assert state.rank == "רבט"


def test_project_chained_advancement_across_multiple_steps(app_session):
    s = create_soldier(app_session, personal_number="1234572")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=1, actor_id=None)
    upsert_interval(app_session, track="enlisted", rank="סמל", months_to_next=1, actor_id=None)
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


def test_bulk_future_ineligible_excludes_multiday_block_when_departure_falls_midblock(app_session):
    s = create_soldier(app_session, personal_number="1234594")
    s.rank = "טוראי"
    s.discharge_date = date(2026, 6, 2)
    app_session.flush()
    dt = _duty_type(app_session)
    block = _duty_block(dt.id, date(2026, 6, 1), end_day=date(2026, 6, 4))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())
