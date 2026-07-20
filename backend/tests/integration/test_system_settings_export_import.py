from __future__ import annotations

from tests.helpers import auth_headers, create_soldier


def test_export_returns_current_settings(client, admin_session):
    admin = create_soldier(admin_session, personal_number="7940001", role="admin")
    resp = client.get("/api/admin/system-settings/export", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert "settings" in resp.json()


def test_import_applies_settings(client, admin_session):
    admin = create_soldier(admin_session, personal_number="7940002", role="admin")
    resp = client.post(
        "/api/admin/system-settings/import",
        json={"settings": {"eligibility.mitvahim_months": 9}},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["eligibility.mitvahim_months"] == 9


def test_import_rejects_invalid_density_settings(client, admin_session):
    admin = create_soldier(admin_session, personal_number="7940003", role="admin")
    resp = client.post(
        "/api/admin/system-settings/import",
        json={"settings": {
            "algorithm.max_duties_per_window": 9,
            "algorithm.max_total_duties_per_window": 7,
        }},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "t_exceeds_r"
