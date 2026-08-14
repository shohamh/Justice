from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RankAdvancementInterval
from app.services.rank_advancement import (
    advances_on_career_entry, compute_next_rank_date, get_interval_months, get_next_rank, get_track,
    upsert_interval, set_interval_and_recompute, get_rank_ladder,
)
from tests.helpers import create_soldier


def test_get_track_enlisted():
    assert get_track("טוראי") == "enlisted"


def test_get_track_officer():
    assert get_track("סגן") == "officer"


def test_get_track_unknown_rank_returns_none():
    assert get_track("not_a_rank") is None


def test_get_next_rank_mid_ladder():
    assert get_next_rank("טוראי") == "רבט"


def test_get_next_rank_top_of_enlisted_ladder_returns_none():
    assert get_next_rank("רנג") is None


def test_get_next_rank_top_of_officer_ladder_returns_none():
    assert get_next_rank("רב אלוף") is None


def test_get_next_rank_never_crosses_enlisted_to_officer():
    # top enlisted rank has no "next" even though the officer ladder starts
    # right after it conceptually -- crossing is never automatic.
    assert get_next_rank("רנג") is None


def test_get_interval_months_returns_configured_value(app_session):
    app_session.add(RankAdvancementInterval(track="enlisted", rank="טוראי", months_to_next=4))
    app_session.flush()
    assert get_interval_months(app_session, track="enlisted", rank="טוראי") == 4


def test_get_interval_months_returns_none_when_unconfigured(app_session):
    assert get_interval_months(app_session, track="enlisted", rank="טוראי") is None


def test_compute_next_rank_date_adds_months(app_session):
    app_session.add(RankAdvancementInterval(track="enlisted", rank="טוראי", months_to_next=4))
    app_session.flush()
    result = compute_next_rank_date(app_session, rank="טוראי", since=date(2026, 1, 1))
    assert result == date(2026, 5, 1)


def test_compute_next_rank_date_none_when_unconfigured(app_session):
    result = compute_next_rank_date(app_session, rank="טוראי", since=date(2026, 1, 1))
    assert result is None


def test_upsert_interval_creates_row(app_session):
    row = upsert_interval(
        app_session, track="enlisted", rank="טוראי", months_to_next=4,
        advance_on_career_entry=False, actor_id=None,
    )
    assert row.months_to_next == 4
    app_session.flush()
    fetched = app_session.execute(
        select(RankAdvancementInterval).where(RankAdvancementInterval.rank == "טוראי")
    ).scalar_one()
    assert fetched.months_to_next == 4


def test_upsert_interval_updates_existing_row(app_session):
    upsert_interval(
        app_session, track="enlisted", rank="טוראי", months_to_next=4,
        advance_on_career_entry=False, actor_id=None,
    )
    app_session.flush()
    upsert_interval(
        app_session, track="enlisted", rank="טוראי", months_to_next=6,
        advance_on_career_entry=False, actor_id=None,
    )
    app_session.flush()
    rows = app_session.execute(
        select(RankAdvancementInterval).where(RankAdvancementInterval.rank == "טוראי")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].months_to_next == 6


def test_set_interval_and_recompute_updates_non_overridden_soldiers(app_session):
    s = create_soldier(app_session, personal_number="1234567")
    s.rank = "טוראי"
    s.current_rank_since = date(2026, 1, 1)
    s.next_rank_date_overridden = False
    app_session.flush()

    count = set_interval_and_recompute(
        app_session, track="enlisted", rank="טוראי", months_to_next=4,
        advance_on_career_entry=False, actor_id=None,
    )

    assert count == 1
    assert s.next_rank_date == date(2026, 5, 1)


def test_set_interval_and_recompute_skips_overridden_soldiers(app_session):
    s = create_soldier(app_session, personal_number="1234568")
    s.rank = "טוראי"
    s.current_rank_since = date(2026, 1, 1)
    s.next_rank_date = date(2099, 1, 1)
    s.next_rank_date_overridden = True
    app_session.flush()

    set_interval_and_recompute(
        app_session, track="enlisted", rank="טוראי", months_to_next=4,
        advance_on_career_entry=False, actor_id=None,
    )

    assert s.next_rank_date == date(2099, 1, 1)


def test_set_interval_and_recompute_ignores_other_ranks(app_session):
    s = create_soldier(app_session, personal_number="1234569")
    s.rank = "רבט"
    s.current_rank_since = date(2026, 1, 1)
    s.next_rank_date = None
    s.next_rank_date_overridden = False
    app_session.flush()

    set_interval_and_recompute(
        app_session, track="enlisted", rank="טוראי", months_to_next=4,
        advance_on_career_entry=False, actor_id=None,
    )

    assert s.next_rank_date is None


def test_get_rank_ladder_shape(app_session):
    upsert_interval(
        app_session, track="enlisted", rank="טוראי", months_to_next=4,
        advance_on_career_entry=False, actor_id=None,
    )
    ladder = get_rank_ladder(app_session)
    assert ladder["enlisted"][0] == {
        "rank": "טוראי", "months_to_next": 4, "advance_on_career_entry": False,
    }
    assert ladder["enlisted"][-1]["months_to_next"] is None
    assert ladder["officer"][0]["rank"] == "סגמ"


def test_get_track_kama_is_none():
    assert get_track("קמא") is None


def test_get_next_rank_kama_is_none():
    assert get_next_rank("קמא") is None


def test_get_track_kab_is_officer_academic():
    assert get_track("קאב") == "officer_academic"


def test_get_track_kam_is_officer_academic():
    assert get_track("קאם") == "officer_academic"


def test_get_next_rank_kab_goes_to_kam():
    assert get_next_rank("קאב") == "קאם"


def test_get_next_rank_kam_is_top_of_academic_ladder():
    assert get_next_rank("קאם") is None


def test_regular_officer_ladder_skips_kab_and_kam():
    # סגן -> סרן directly, not via קאב/קאם
    assert get_next_rank("סגן") == "סרן"
    assert get_next_rank("סרן") == "רסן"


def test_get_track_sgan_is_officer_not_academic():
    assert get_track("סגן") == "officer"


def test_upsert_interval_persists_advance_on_career_entry(app_session):
    row = upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    assert row.advance_on_career_entry is True
    app_session.flush()
    fetched = app_session.execute(
        select(RankAdvancementInterval).where(RankAdvancementInterval.rank == "קאב")
    ).scalar_one()
    assert fetched.advance_on_career_entry is True


def test_advances_on_career_entry_true(app_session):
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    assert advances_on_career_entry(app_session, track="officer_academic", rank="קאב") is True


def test_advances_on_career_entry_false_when_unconfigured(app_session):
    assert advances_on_career_entry(app_session, track="officer_academic", rank="קאב") is False


def test_get_rank_ladder_has_three_tracks_and_flag(app_session):
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    ladder = get_rank_ladder(app_session)
    assert set(ladder.keys()) == {"enlisted", "officer", "officer_academic"}
    kab_entry = next(e for e in ladder["officer_academic"] if e["rank"] == "קאב")
    assert kab_entry == {"rank": "קאב", "months_to_next": None, "advance_on_career_entry": True}
    assert "קמא" not in [e["rank"] for e in ladder["officer"]]
