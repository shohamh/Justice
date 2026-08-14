from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_get_rank_ladder_returns_both_tracks(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="rank_ladder_001")

    resp = client.get("/api/soldiers/rank-ladder", headers=auth_headers(soldier))

    assert resp.status_code == 200
    body = resp.json()
    assert body["enlisted"][0]["rank"] == "טוראי"
    assert body["officer"][0]["rank"] == "קמא"


def test_public_rank_ladder_readable_without_auth(client: TestClient):
    """The public /register page (an unauthenticated route) populates its
    mandatory rank picker from this endpoint, so it must work with no token."""
    resp = client.get("/api/auth/rank-ladder")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enlisted"][0]["rank"] == "טוראי"
    assert body["officer"][0]["rank"] == "קמא"


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
