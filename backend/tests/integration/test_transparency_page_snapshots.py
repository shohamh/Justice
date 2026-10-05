"""PostgreSQL parity checks for persisted transparency pages."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import jwt
from sqlalchemy import text

from app.services import transparency_read_model
from app.settings import get_settings
from tests.helpers import auth_headers, create_node, create_soldier


def test_persisted_pages_keep_export_values_filters_and_sort_ties(client, admin_session):
    admin = create_soldier(admin_session, personal_number="page-parity-admin", role="admin")
    parent = create_node(admin_session, level="department", name="Parent")
    child = create_node(admin_session, level="team", name="Child", parent=parent)
    other = create_node(admin_session, level="department", name="Other")
    alpha = create_soldier(admin_session, personal_number="page-parity-alpha", full_name="Alpha", hierarchy_node_id=parent.id)
    beta = create_soldier(admin_session, personal_number="page-parity-beta", full_name="Beta", hierarchy_node_id=child.id)
    gamma = create_soldier(admin_session, personal_number="page-parity-gamma", full_name="Gamma", hierarchy_node_id=other.id)
    alpha.rank = "A"
    beta.rank = "B"
    beta.is_officer = True
    beta.mandatory_end_date = date.today() + timedelta(days=30)
    gamma.rank = "B"
    admin_session.commit()

    export = client.get("/api/scoring/transparency", headers=auth_headers(admin))
    assert export.status_code == 200
    exported = export.json()["rows"]
    assert {str(soldier.id) for soldier in (admin, alpha, beta, gamma)} == {
        row["soldier_id"] for row in exported
    }

    cases = (
        ({"sort": "burden_share", "descending": "true"}, exported,
         lambda row: (row["burden_share"], row["soldier_id"])),
        ({"sort": "name", "descending": "false"}, exported,
         lambda row: (row["full_name"].casefold(), row["soldier_id"])),
        ({"node_id": str(parent.id), "sort": "name", "descending": "false"},
         [row for row in exported if row["soldier_id"] in {str(alpha.id), str(beta.id)}],
         lambda row: (row["full_name"].casefold(), row["soldier_id"])),
        ({"officer_filter": "officer", "sort": "name", "descending": "false"},
         [row for row in exported if row["is_officer"]],
         lambda row: (row["full_name"].casefold(), row["soldier_id"])),
        ({"sort": "rank", "rank_order": ["B", "A"], "descending": "false"},
         exported,
         lambda row: ({"B": 0, "A": 1}.get(row["rank"], 3), row["soldier_id"])),
        ({"rank_filter": "B", "search": "a", "sort": "name", "descending": "false"},
         [row for row in exported if row["rank"] == "B" and "a" in row["full_name"].casefold()],
         lambda row: (row["full_name"].casefold(), row["soldier_id"])),
        ({"service_type": next(row["service_type"] for row in exported if row["soldier_id"] == str(beta.id)),
          "sort": "name", "descending": "false"},
         [row for row in exported if row["service_type"] == next(item["service_type"] for item in exported if item["soldier_id"] == str(beta.id))],
         lambda row: (row["full_name"].casefold(), row["soldier_id"])),
    )
    for params, candidates, key in cases:
        expected = sorted(candidates, key=key, reverse=params["descending"] == "true")
        # For equal primary values, UUID remains ascending in both directions.
        if params["sort"] == "burden_share":
            expected = sorted(candidates, key=lambda row: row["soldier_id"])
            expected.sort(key=lambda row: row["burden_share"], reverse=True)
        items = []
        cursor = None
        while True:
            response = client.get(
                "/api/scoring/transparency/page",
                params={**params, "page_size": 1, **({"cursor": cursor} if cursor else {})},
                headers=auth_headers(admin),
            )
            assert response.status_code == 200, response.text
            body = response.json()
            items.extend(body["items"])
            assert body["can_see_exemption_aggregates"] == export.json()["can_see_exemption_aggregates"]
            if params.get("rank_filter"):
                assert body["summary"]["row_count"] == len(exported)
            else:
                assert body["summary"]["row_count"] == len(candidates)
            cursor = body["next_cursor"]
            if not cursor:
                break
        assert [{key: value for key, value in row.items() if key != "row_num"} for row in items] == expected


def test_persisted_scoped_page_matches_complete_scoped_export(client, admin_session):
    node = create_node(admin_session, level="department", name="Scoped")
    outside = create_node(admin_session, level="department", name="Outside")
    manager = create_soldier(
        admin_session, personal_number="scoped-page-manager", role="duty_manager",
        hierarchy_node_id=node.id,
    )
    create_soldier(admin_session, personal_number="scoped-page-member", hierarchy_node_id=node.id)
    create_soldier(admin_session, personal_number="scoped-page-outside", hierarchy_node_id=outside.id)
    admin_session.commit()

    export = client.get("/api/scoring/transparency", headers=auth_headers(manager))
    assert export.status_code == 200
    page = client.get(
        "/api/scoring/transparency/page",
        params={"sort": "num", "descending": "false", "page_size": 100},
        headers=auth_headers(manager),
    )
    assert page.status_code == 200
    body = page.json()
    assert body["can_see_exemption_aggregates"] == export.json()["can_see_exemption_aggregates"]
    assert body["summary"]["row_count"] == len(export.json()["rows"])
    assert [{key: value for key, value in row.items() if key != "row_num"} for row in body["items"]] == export.json()["rows"]
    assert [row["row_num"] for row in body["items"]] == list(range(1, len(body["items"]) + 1))


def test_default_v2_cursor_continues_its_saved_snapshot_after_read_model_appears(
    client, admin_session, monkeypatch,
):
    import app.routes.scoring as scoring_route

    settings = scoring_route.get_settings()
    monkeypatch.setattr(scoring_route, "get_settings", lambda: SimpleNamespace(
        jwt_secret=settings.jwt_secret,
        jwt_algorithm=settings.jwt_algorithm,
        transparency_read_model_enabled=False,
    ))
    admin = create_soldier(admin_session, personal_number="v2-model-appears-admin", role="admin")
    first_soldier = create_soldier(admin_session, personal_number="v2-model-appears-first")
    second_soldier = create_soldier(admin_session, personal_number="v2-model-appears-second")

    def row(soldier, burden_share):
        return {
            "soldier_id": soldier.id,
            "full_name": soldier.full_name,
            "node_id": soldier.hierarchy_node_id,
            "node_name": None,
            "enrolled_at": date(2020, 1, 1),
            "active_days": 10,
            "shift_count": 1,
            "rank": None,
            "is_officer": False,
            "service_type": None,
            "cumulative_score": Decimal("2.0"),
            "score_per_day": Decimal("0.2"),
            "normalised_score": Decimal("1.0"),
            "is_globally_exempted": False,
            "burden_share": burden_share,
            "c_over_d": 1.0,
            "burden_share_offset_raw": 0,
            "exemptions_display": "",
            "exemptions_visible": False,
            "exemptions": [],
            "has_global_exemption": None,
            "has_partial_exemption": None,
            "has_temporary_exemption": None,
        }

    monkeypatch.setattr(scoring_route.svc, "transparency_rows", lambda _session, *, viewer: {
        "rows": [row(first_soldier, 0.9), row(second_soldier, 0.5)],
        "can_see_exemption_aggregates": True,
    })
    first = client.get(
        "/api/scoring/transparency/page", params={"page_size": 1}, headers=auth_headers(admin),
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor
    payload = jwt.decode(
        cursor,
        get_settings().jwt_secret,
        algorithms=[get_settings().jwt_algorithm],
        options={"verify_exp": False},
    )
    assert payload["purpose"] == "transparency-page-v2"
    snapshot_id = uuid.UUID(payload["snapshot_id"])

    source_generation, source_snapshot = transparency_read_model.capture_source_state(admin_session)
    admin_session.execute(text("""
        INSERT INTO transparency_read_model_generations
          (id, source_generation, source_snapshot, as_of, normalization_denominator,
           ready, published_at)
        VALUES (:id, :generation, :snapshot, :as_of, 1, true, now())
    """), {
        "id": uuid.uuid4(), "generation": source_generation,
        "snapshot": source_snapshot, "as_of": date.today(),
    })
    admin_session.commit()

    second = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "cursor": cursor},
        headers=auth_headers(admin),
    )
    assert second.status_code == 200, second.text
    assert second.json()["items"][0]["soldier_id"] == str(second_soldier.id)
    assert second.json()["items"][0]["row_num"] == 2
    assert second.json()["next_cursor"] is None
    assert admin_session.execute(text(
        "SELECT ready FROM transparency_page_snapshots WHERE id = :id"
    ), {"id": snapshot_id}).scalar_one() is True
