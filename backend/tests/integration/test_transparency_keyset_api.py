"""Endpoint parity and cursor-contract checks for the default transparency keyset path."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import jwt
import pytest
from sqlalchemy import text

from app.auth.authz import scope_root_ids
from app.db.models import ExemptionType, SoldierExemption, SystemSetting
from app.services import transparency_read_model
from app.settings import get_settings
from tests.helpers import auth_headers, create_node, create_soldier


def _insert_read_model(session, rows: list[dict]) -> uuid.UUID:
    source_generation, source_snapshot = transparency_read_model.capture_source_state(session)
    generation_id = uuid.uuid4()
    session.execute(text("""
        INSERT INTO transparency_read_model_generations
          (id, source_generation, source_snapshot, as_of, normalization_denominator,
           ready, published_at)
        VALUES (:id, :generation, :snapshot, :as_of, 1, true, now())
    """), {
        "id": generation_id,
        "generation": source_generation,
        "snapshot": source_snapshot,
        "as_of": date.today(),
    })
    session.execute(text("""
        INSERT INTO transparency_read_model_rows
          (generation_id, soldier_id, burden_share, cumulative_score, score_per_day,
           normalised_score, c_over_d, active_days, shift_count, burden_share_offset_raw,
           full_name, node_id, node_name, enrolled_at, rank, is_officer, service_type,
           is_globally_exempted)
        VALUES
          (:generation_id, :soldier_id, :burden_share, :cumulative_score, :score_per_day,
           :normalised_score, :c_over_d, :active_days, :shift_count, :burden_share_offset_raw,
           :full_name, :node_id, :node_name, :enrolled_at, :rank, :is_officer, :service_type,
           :is_globally_exempted)
    """), [{**row, "generation_id": generation_id} for row in rows])
    session.commit()
    return generation_id


def _model_row(soldier, burden_share: str, *, cumulative: str = "2", active_days: int = 10) -> dict:
    return {
        "soldier_id": soldier.id,
        "burden_share": Decimal(burden_share),
        "cumulative_score": Decimal(cumulative),
        "score_per_day": Decimal(cumulative) / Decimal(active_days),
        "normalised_score": Decimal(cumulative) / Decimal(active_days),
        "c_over_d": Decimal("1.25"),
        "active_days": active_days,
        "shift_count": 2,
        "burden_share_offset_raw": 3,
        "full_name": soldier.full_name,
        "node_id": soldier.hierarchy_node_id,
        "node_name": None,
        "enrolled_at": soldier.enrolled_at,
        "rank": soldier.rank,
        "is_officer": soldier.is_officer,
        "service_type": None,
        "is_globally_exempted": False,
    }


def _decode_cursor(cursor: str) -> dict:
    return jwt.decode(
        cursor,
        get_settings().jwt_secret,
        algorithms=[get_settings().jwt_algorithm],
        options={"verify_exp": False},
    )


def test_default_keyset_pages_ties_continuously_and_summarizes_full_visible_set(
    client, admin_session, monkeypatch,
):
    import app.routes.scoring as scoring_route

    admin = create_soldier(admin_session, personal_number="keyset-page-admin", role="admin")
    soldiers = [
        create_soldier(admin_session, personal_number=f"keyset-page-{index}", full_name=f"Person {index}")
        for index in range(4)
    ]
    ties = sorted(soldiers[1:3], key=lambda soldier: str(soldier.id))
    generation_id = _insert_read_model(admin_session, [
        _model_row(admin, "0.90", cumulative="10", active_days=20),
        _model_row(soldiers[0], "0.70", cumulative="8", active_days=10),
        _model_row(ties[0], "0.50", cumulative="6", active_days=10),
        _model_row(ties[1], "0.50", cumulative="4", active_days=10),
        _model_row(soldiers[3], "0.10", cumulative="2", active_days=10),
    ])
    monkeypatch.setattr(
        scoring_route.svc,
        "transparency_rows",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full-population fallback was used")),
    )

    pages = []
    cursor = None
    while True:
        response = client.get(
            "/api/scoring/transparency/page",
            params={"page_size": 2, **({"cursor": cursor} if cursor else {})},
            headers=auth_headers(admin),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        pages.append(body)
        if not body["next_cursor"]:
            break
        token = _decode_cursor(body["next_cursor"])
        assert token["purpose"] == "transparency-page-v3"
        assert token["model_id"] == str(generation_id)
        assert isinstance(token["last_burden_share"], str)
        assert token["emitted_count"] == sum(len(page["items"]) for page in pages)
        cursor = body["next_cursor"]

    items = [item for page in pages for item in page["items"]]
    assert [item["soldier_id"] for item in items] == [
        str(admin.id), str(soldiers[0].id), str(ties[0].id), str(ties[1].id), str(soldiers[3].id),
    ]
    assert [item["row_num"] for item in items] == [1, 2, 3, 4, 5]
    assert [page["has_more"] for page in pages] == [True, True, False]
    assert [page["summary"]["row_count"] for page in pages] == [5, 5, 5]
    summary = pages[0]["summary"]
    assert {key: value for key, value in summary.items() if key != "burden_share_cv"} == {
        "row_count": 5,
        "average_cumulative": 6.0,
        "average_active_days": 12,
        "average_score_per_day": 0.5,
        "average_normalised": 0.5,
        "burden_share_mean": 0.54,
        "burden_share_stddev": 0.265329983228432,
        "burden_share_min": 0.1,
        "burden_share_max": 0.9,
        "burden_share_offset_min": 3,
        "burden_share_offset_max": 3,
    }
    assert summary["burden_share_cv"] == pytest.approx(0.4913518207933926)


def test_scoped_keyset_includes_self_and_redacts_exemptions_outside_raw_roots(
    client, admin_session,
):
    root = create_node(admin_session, level="department", name="Keyset Scope")
    child = create_node(admin_session, level="team", name="Keyset Child", parent=root)
    outside = create_node(admin_session, level="department", name="Keyset Outside")
    viewer = create_soldier(
        admin_session, personal_number="keyset-scope-manager", role="duty_manager",
        hierarchy_node_id=root.id,
    )
    member = create_soldier(admin_session, personal_number="keyset-scope-member", hierarchy_node_id=child.id)
    outsider = create_soldier(admin_session, personal_number="keyset-scope-outsider", hierarchy_node_id=outside.id)
    exemption_type = ExemptionType(name="keyset-scope-medical", is_global=True)
    admin_session.add(exemption_type)
    admin_session.flush()
    admin_session.add_all([
        SoldierExemption(
            soldier_id=member.id, exemption_type_id=exemption_type.id,
            start_date=date.today(), end_date=None,
        ),
        SoldierExemption(
            soldier_id=outsider.id, exemption_type_id=exemption_type.id,
            start_date=date.today(), end_date=None,
        ),
    ])
    admin_session.commit()
    _insert_read_model(admin_session, [
        _model_row(viewer, "0.90"),
        _model_row(member, "0.80"),
        _model_row(outsider, "0.70"),
    ])

    response = client.get(
        "/api/scoring/transparency/page", params={"page_size": 1}, headers=auth_headers(viewer),
    )
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["can_see_exemption_aggregates"] is True
    assert first["items"][0]["soldier_id"] == str(viewer.id)
    assert first["items"][0]["row_num"] == 1
    assert first["next_cursor"]

    second = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "cursor": first["next_cursor"]},
        headers=auth_headers(viewer),
    )
    assert second.status_code == 200, second.text
    item = second.json()["items"][0]
    assert item["soldier_id"] == str(member.id)
    assert item["row_num"] == 2
    assert item["exemptions_visible"] is True
    assert item["exemptions_display"]
    assert len(item["exemptions"]) == 1
    assert item["exemptions"][0]["is_global"] is True
    assert scope_root_ids(admin_session, viewer) == {root.id}
    assert str(outsider.id) not in {item["soldier_id"] for item in first["items"] + second.json()["items"]}


def test_default_request_without_ready_read_model_keeps_snapshot_fallback(client, admin_session, monkeypatch):
    import app.routes.scoring as scoring_route

    admin = create_soldier(admin_session, personal_number="keyset-fallback-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="keyset-fallback-soldier")
    row = _model_row(soldier, "0.25")
    row.update({
        "exemptions_display": "",
        "exemptions_visible": False,
        "exemptions": [],
        "has_global_exemption": None,
        "has_partial_exemption": None,
        "has_temporary_exemption": None,
    })
    fallback_calls = []
    monkeypatch.setattr(scoring_route.svc, "transparency_rows", lambda *_args, **_kwargs: (
        fallback_calls.append(True) or {
            "rows": [dict(row) for _ in range(101)], "can_see_exemption_aggregates": True,
        }
    ))
    response = client.get(
        "/api/scoring/transparency/page", headers=auth_headers(admin),
    )
    assert response.status_code == 200, response.text
    cursor = response.json()["next_cursor"]
    assert cursor
    assert _decode_cursor(cursor)["purpose"] == "transparency-page-v2"
    assert fallback_calls
    assert response.json()["items"][0]["soldier_id"] == str(soldier.id)


def test_visible_rank_wide_rows_keep_exemption_labels_and_aggregates_redacted(client, admin_session):
    root = create_node(admin_session, level="department", name="Keyset Rank Visible")
    viewer = create_soldier(admin_session, personal_number="keyset-rank-viewer")
    target = create_soldier(admin_session, personal_number="keyset-rank-target", hierarchy_node_id=root.id)
    admin_session.add(SystemSetting(key="transparency.min_visible_level", value="every_soldier"))
    exemption_type = ExemptionType(name="keyset-hidden-medical", is_global=True)
    admin_session.add(exemption_type)
    admin_session.flush()
    admin_session.add(SoldierExemption(
        soldier_id=target.id, exemption_type_id=exemption_type.id,
        start_date=date.today(), end_date=None,
    ))
    admin_session.commit()
    _insert_read_model(admin_session, [
        _model_row(viewer, "0.9"),
        {**_model_row(target, "0.8"), "is_globally_exempted": True},
    ])

    response = client.get(
        "/api/scoring/transparency/page", headers=auth_headers(viewer),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["row_count"] == 2
    assert body["can_see_exemption_aggregates"] is False
    item = next(row for row in body["items"] if row["soldier_id"] == str(target.id))
    assert item["is_globally_exempted"] is True
    assert item["exemptions_visible"] is False
    assert item["exemptions_display"] == "\u05d7\u05e1\u05d5\u05d9"
    assert item["exemptions"] == []
    assert item["has_global_exemption"] is None
    assert item["has_partial_exemption"] is None
    assert item["has_temporary_exemption"] is None


def test_signed_but_malformed_keyset_cursor_is_rejected_as_invalid(client, admin_session):
    admin = create_soldier(admin_session, personal_number="keyset-malformed-admin", role="admin")
    malformed = jwt.encode({
        "purpose": "transparency-page-v3",
        "binding": "not-the-current-binding",
        "model_id": "not-a-uuid",
        "source_generation": 1,
        "as_of": str(date.today()),
        "last_burden_share": "not-a-decimal",
        "last_soldier_id": "not-a-uuid",
        "emitted_count": 1,
        "exp": 4102444800,
    }, get_settings().jwt_secret, algorithm=get_settings().jwt_algorithm)
    response = client.get(
        "/api/scoring/transparency/page", params={"cursor": malformed}, headers=auth_headers(admin),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_cursor"

    tampered = malformed[:-1] + ("a" if malformed[-1] != "a" else "b")
    signature_failure = client.get(
        "/api/scoring/transparency/page", params={"cursor": tampered}, headers=auth_headers(admin),
    )
    assert signature_failure.status_code == 400
    assert signature_failure.json()["detail"] == "invalid_cursor"


def test_keyset_cursor_rejects_changed_binding_and_stale_source(client, admin_session):
    admin = create_soldier(admin_session, personal_number="keyset-stale-admin", role="admin")
    soldiers = [
        create_soldier(admin_session, personal_number=f"keyset-stale-{index}")
        for index in range(3)
    ]
    _insert_read_model(admin_session, [
        _model_row(soldiers[0], "0.9"), _model_row(soldiers[1], "0.8"), _model_row(soldiers[2], "0.7"),
    ])
    first = client.get(
        "/api/scoring/transparency/page", params={"page_size": 1}, headers=auth_headers(admin),
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert _decode_cursor(cursor)["purpose"] == "transparency-page-v3"

    changed_binding = client.get(
        "/api/scoring/transparency/page", params={"page_size": 2, "cursor": cursor},
        headers=auth_headers(admin),
    )
    assert changed_binding.status_code == 400
    assert changed_binding.json()["detail"] == "invalid_cursor"

    soldiers[0].full_name = "Source changed after page one"
    admin_session.commit()
    stale = client.get(
        "/api/scoring/transparency/page", params={"page_size": 1, "cursor": cursor},
        headers=auth_headers(admin),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "stale_cursor"


def test_keyset_cursor_returns_forbidden_after_transparency_scope_is_revoked(client, admin_session):
    root = create_node(admin_session, level="department", name="Keyset Revoked")
    viewer = create_soldier(
        admin_session, personal_number="keyset-revoked-manager", role="duty_manager",
        hierarchy_node_id=root.id,
    )
    member = create_soldier(admin_session, personal_number="keyset-revoked-member", hierarchy_node_id=root.id)
    _insert_read_model(admin_session, [_model_row(viewer, "0.9"), _model_row(member, "0.8")])
    first = client.get(
        "/api/scoring/transparency/page", params={"page_size": 1}, headers=auth_headers(viewer),
    )
    assert first.status_code == 200, first.text
    assert first.json()["next_cursor"]

    admin_session.execute(text("DELETE FROM duty_manager_scope WHERE duty_manager_id = :id"), {"id": viewer.id})
    admin_session.commit()
    revoked = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "cursor": first.json()["next_cursor"]},
        headers=auth_headers(viewer),
    )
    assert revoked.status_code == 403
    assert revoked.json()["detail"] == "transparency_hidden"
