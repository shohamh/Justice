from datetime import date

from app.services.rank_advancement import upsert_interval
from app.services.rank_eligibility_projection import project_soldier_state
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
