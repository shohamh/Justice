from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_soldier


def test_submit_exemption_request_rejects_missing_reason(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7800010")
    et = ExemptionType(name="פטור-api-reason", is_commander_exemption=False)
    admin_session.add(et)
    admin_session.commit()

    r = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(s),
        json={
            "exemption_type_id": str(et.id),
            "start_date": (date.today() + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 422
