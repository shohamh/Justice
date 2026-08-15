from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_get_rank_ladder_returns_both_tracks(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="rank_ladder_001")

    resp = client.get("/api/soldiers/rank-ladder", headers=auth_headers(soldier))

    assert resp.status_code == 200
    body = resp.json()
    assert body["enlisted"][0]["rank"] == "טוראי"
    assert body["officer"][0]["rank"] == "סגמ"
    assert body["officer_academic"][0]["rank"] == "קמא"
    assert [e["rank"] for e in body["officer_academic"]] == [
        "קמא", "קאב", "סגן", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף", "קאם",
    ]


def test_public_rank_ladder_readable_without_auth(client: TestClient):
    """The public /register page (an unauthenticated route) populates its
    mandatory rank picker from this endpoint, so it must work with no token."""
    resp = client.get("/api/auth/rank-ladder")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enlisted"][0]["rank"] == "טוראי"
    assert body["officer"][0]["rank"] == "סגמ"
    assert body["officer_academic"][0]["rank"] == "קמא"


def test_put_rank_advancement_intervals_requires_admin(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="rank_ladder_002")

    resp = client.put(
        "/api/soldiers/rank-advancement-intervals",
        json=[{"track": "enlisted", "rank": "טוראי", "months_to_next": 4}],
        headers=auth_headers(soldier),
    )

    assert resp.status_code == 403


def test_put_rank_advancement_intervals_updates_config(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="rank_ladder_003", role="admin")

    resp = client.put(
        "/api/soldiers/rank-advancement-intervals",
        json=[{"track": "enlisted", "rank": "טוראי", "months_to_next": 4}],
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    body = resp.json()
    entry = next(r for r in body["enlisted"] if r["rank"] == "טוראי")
    assert entry["months_to_next"] == 4

    ladder_resp = client.get("/api/soldiers/rank-ladder", headers=auth_headers(admin))
    entry = next(r for r in ladder_resp.json()["enlisted"] if r["rank"] == "טוראי")
    assert entry["months_to_next"] == 4


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"track": "bogus", "rank": "טוראי", "months_to_next": 4}, id="bad_track"),
        pytest.param({"track": "enlisted", "rank": "סגן", "months_to_next": 4}, id="rank_wrong_track"),
        pytest.param({"track": "enlisted", "rank": "לא-דרגה", "months_to_next": 4}, id="rank_not_a_rank"),
        pytest.param({"track": "enlisted", "rank": "טוראי", "months_to_next": 0}, id="zero_months"),
        pytest.param({"track": "enlisted", "rank": "טוראי", "months_to_next": -1}, id="negative_months"),
    ],
)
def test_put_rank_advancement_intervals_rejects_invalid_payloads(
    client: TestClient, admin_session: Session, payload: dict
):
    """Junk (track, rank) rows are invisible in get_rank_ladder()'s output and
    could never be cleaned up from the UI; months_to_next <= 1 either spins the
    projection chain-walk or walks next_rank_date backwards forever."""
    admin = create_soldier(
        admin_session, personal_number=f"rank_ladder_bad_{uuid.uuid4().hex[:8]}", role="admin",
    )

    with patch(
        "app.routes.rank_advancement.set_interval_and_recompute"
    ) as mock_set:
        resp = client.put(
            "/api/soldiers/rank-advancement-intervals",
            json=[payload],
            headers=auth_headers(admin),
        )

    assert resp.status_code == 422, resp.text
    mock_set.assert_not_called()


def test_put_rank_advancement_intervals_persists_academic_track_and_flag(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="rank_ladder_004", role="admin")

    resp = client.put(
        "/api/soldiers/rank-advancement-intervals",
        json=[{"track": "officer_academic", "rank": "קאב", "months_to_next": None, "advance_on_career_entry": True}],
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    entry = next(e for e in resp.json()["officer_academic"] if e["rank"] == "קאב")
    assert entry["advance_on_career_entry"] is True


def test_put_rank_advancement_intervals_accepts_shared_sgan_on_both_tracks(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="rank_ladder_006", role="admin")

    resp = client.put(
        "/api/soldiers/rank-advancement-intervals",
        json=[
            {"track": "officer", "rank": "סגן", "months_to_next": 12, "advance_on_career_entry": False},
            {"track": "officer_academic", "rank": "סגן", "months_to_next": 6, "advance_on_career_entry": False},
        ],
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    regular = next(e for e in resp.json()["officer"] if e["rank"] == "סגן")
    academic = next(e for e in resp.json()["officer_academic"] if e["rank"] == "סגן")
    assert regular["months_to_next"] == 12
    assert academic["months_to_next"] == 6


def test_put_rank_advancement_intervals_rejects_kab_under_officer_track(
    client: TestClient, admin_session: Session
):
    # קאב no longer belongs to the regular officer ladder
    admin = create_soldier(admin_session, personal_number="rank_ladder_005", role="admin")

    resp = client.put(
        "/api/soldiers/rank-advancement-intervals",
        json=[{"track": "officer", "rank": "קאב", "months_to_next": 6, "advance_on_career_entry": False}],
        headers=auth_headers(admin),
    )

    assert resp.status_code == 422
