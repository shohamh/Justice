from __future__ import annotations

import uuid

from tests.helpers import auth_headers, create_node, create_soldier


def test_get_potential_requires_auth(client):
    resp = client.get("/api/potential", params={"node_id": str(uuid.uuid4())})
    assert resp.status_code == 401


def test_get_potential_as_duty_manager(client, admin_session):
    node = create_node(admin_session, level="פלוגה", name="Route Test Co")
    dm = create_soldier(
        admin_session, personal_number="5000900", role="duty_manager", hierarchy_node_id=node.id,
    )
    admin_session.commit()

    resp = client.get(
        "/api/potential",
        params={"node_id": str(node.id), "reference_date": "2026-07-03"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["final_potential"] == 0


def test_get_potential_includes_partial_exemption_fields(client, admin_session):
    node = create_node(admin_session, level="פלוגה", name="Route Test Partial Co")
    dm = create_soldier(
        admin_session, personal_number="5000903", role="duty_manager", hierarchy_node_id=node.id,
    )
    admin_session.commit()

    resp = client.get(
        "/api/potential",
        params={"node_id": str(node.id), "reference_date": "2026-07-03"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["partial_exemption_count"] == 0
    assert len(body["soldiers"]) == 1
    assert body["soldiers"][0]["partial_exemption_names"] is None


def test_create_modifier_route_requires_reason(client, admin_session):
    node = create_node(admin_session, level="פלוגה", name="Mod Route Co")
    dm = create_soldier(
        admin_session, personal_number="5000901", role="duty_manager", hierarchy_node_id=node.id,
    )
    admin_session.commit()

    resp = client.post(
        "/api/potential/modifiers",
        json={
            "hierarchy_node_id": str(node.id), "delta": -10, "reason": "", "start_date": "2026-01-01",
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400


def test_create_and_list_modifier_route(client, admin_session):
    node = create_node(admin_session, level="פלוגה", name="Mod Route Co 2")
    dm = create_soldier(
        admin_session, personal_number="5000902", role="duty_manager", hierarchy_node_id=node.id,
    )
    admin_session.commit()

    resp = client.post(
        "/api/potential/modifiers",
        json={
            "hierarchy_node_id": str(node.id), "delta": -60, "reason": "external duties", "start_date": "2026-01-01", "end_date": None,
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 201

    resp2 = client.get(
        "/api/potential/modifiers",
        params={"hierarchy_node_id": str(node.id)},
        headers=auth_headers(dm),
    )
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1
