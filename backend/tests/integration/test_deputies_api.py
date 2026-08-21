from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_principal_can_create_and_list_their_own_deputy(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"a_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"b_{_uid()}")
    admin_session.commit()

    r = client.post(
        "/api/deputies", headers=auth_headers(principal),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today() + timedelta(days=7)),
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["deputy_id"] == str(deputy.id)
    assert body["deputy_name"] == deputy.full_name

    r2 = client.get(f"/api/deputies?principal_id={principal.id}", headers=auth_headers(principal))
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_other_soldier_cannot_create_a_deputy_for_someone_else(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"c_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"d_{_uid()}")
    other = create_soldier(admin_session, personal_number=f"e_{_uid()}")
    admin_session.commit()

    r = client.post(
        "/api/deputies", headers=auth_headers(other),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today()),
        },
    )
    assert r.status_code == 403


def test_admin_can_create_a_deputy_for_someone_else(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number=f"f_{_uid()}", role="admin")
    principal = create_soldier(admin_session, personal_number=f"g_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"h_{_uid()}")
    admin_session.commit()

    r = client.post(
        "/api/deputies", headers=auth_headers(admin),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today()),
        },
    )
    assert r.status_code == 201, r.text


def test_create_deputy_for_a_non_commander_returns_400(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"i_{_uid()}")  # plain soldier
    deputy = create_soldier(admin_session, personal_number=f"j_{_uid()}")
    admin_session.commit()

    r = client.post(
        "/api/deputies", headers=auth_headers(principal),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today()),
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "principal_lacks_role"


def test_principal_can_revoke_their_own_deputy(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"k_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"l_{_uid()}")
    admin_session.commit()

    created = client.post(
        "/api/deputies", headers=auth_headers(principal),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today()),
        },
    ).json()

    r = client.delete(f"/api/deputies/{created['id']}", headers=auth_headers(principal))
    assert r.status_code == 200

    r2 = client.get(f"/api/deputies?principal_id={principal.id}", headers=auth_headers(principal))
    assert r2.json() == []


def test_other_soldier_cannot_revoke_someone_elses_deputy(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"m_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"n_{_uid()}")
    other = create_soldier(admin_session, personal_number=f"o_{_uid()}")
    admin_session.commit()

    created = client.post(
        "/api/deputies", headers=auth_headers(principal),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today()),
        },
    ).json()

    r = client.delete(f"/api/deputies/{created['id']}", headers=auth_headers(other))
    assert r.status_code == 403
