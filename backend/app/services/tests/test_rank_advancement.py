from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RankAdvancementInterval
from app.services.rank_advancement import (
    compute_next_rank_date, get_interval_months, get_next_rank, get_track,
    upsert_interval,
)


def test_get_track_enlisted():
    assert get_track("טוראי") == "enlisted"


def test_get_track_officer():
    assert get_track("קמא") == "officer"


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
    row = upsert_interval(app_session, track="enlisted", rank="טוראי", months_to_next=4, actor_id=None)
    assert row.months_to_next == 4
    app_session.flush()
    fetched = app_session.execute(
        select(RankAdvancementInterval).where(RankAdvancementInterval.rank == "טוראי")
    ).scalar_one()
    assert fetched.months_to_next == 4


def test_upsert_interval_updates_existing_row(app_session):
    upsert_interval(app_session, track="enlisted", rank="טוראי", months_to_next=4, actor_id=None)
    app_session.flush()
    upsert_interval(app_session, track="enlisted", rank="טוראי", months_to_next=6, actor_id=None)
    app_session.flush()
    rows = app_session.execute(
        select(RankAdvancementInterval).where(RankAdvancementInterval.rank == "טוראי")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].months_to_next == 6
