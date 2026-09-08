from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_soldier


def test_grant_exemption_requires_a_reason(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="exgrant001", role="admin")
    target = create_soldier(admin_session, personal_number="exgrant002")
    exemption_type = ExemptionType(name="חופשה")
    admin_session.add(exemption_type)
    admin_session.commit()

    response = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        json={"exemption_type_id": str(exemption_type.id), "start_date": str(date.today())},
        headers=auth_headers(admin),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(error["loc"][-1] == "reason" for error in detail)
