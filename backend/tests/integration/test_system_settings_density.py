from __future__ import annotations

from tests.helpers import auth_headers, create_soldier


def _admin(session, personal_number: str):
    return create_soldier(session, personal_number=personal_number, role="admin")


def test_put_rejects_T_greater_than_R(client, admin_session):
    admin = _admin(admin_session, "sysset_admin_1")
    resp = client.put(
        "/api/admin/system-settings",
        json={"settings": {
            "algorithm.max_duties_per_window": 9,
            "algorithm.max_total_duties_per_window": 7,
        }},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "t_exceeds_r"


def test_put_rejects_t_ceiling_above_r_ceiling(client, admin_session):
    admin = _admin(admin_session, "sysset_admin_2")
    resp = client.put(
        "/api/admin/system-settings",
        json={"settings": {
            "algorithm.relax_t_ceiling": 12,
            "algorithm.relax_r_ceiling": 11,
        }},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "relax_ceiling_invalid"


def test_put_accepts_valid_density_settings(client, admin_session):
    admin = _admin(admin_session, "sysset_admin_3")
    resp = client.put(
        "/api/admin/system-settings",
        json={"settings": {
            "algorithm.max_duties_per_window": 7,
            "algorithm.max_total_duties_per_window": 10,
            "algorithm.window_days": 14,
            "algorithm.relax_t_ceiling": 9,
            "algorithm.relax_r_ceiling": 11,
        }},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    body = resp.json()["settings"]
    assert body["algorithm.max_total_duties_per_window"] == 10
