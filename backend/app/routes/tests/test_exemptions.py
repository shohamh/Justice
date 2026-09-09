from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_soldier


@pytest.mark.parametrize(
    ("reason_payload", "expected_type", "expected_message"),
    [
        ({}, "missing", "Field required"),
        ({"reason": ""}, "string_too_short", "at least 1 character"),
        ({"reason": "   "}, "value_error", "reason must not be empty"),
    ],
)
def test_grant_exemption_requires_a_reason(
    client: TestClient,
    admin_session: Session,
    reason_payload: dict[str, str],
    expected_type: str,
    expected_message: str,
):
    admin = create_soldier(admin_session, personal_number="exgrant001", role="admin")
    target = create_soldier(admin_session, personal_number="exgrant002")
    exemption_type = ExemptionType(name="חופשה")
    admin_session.add(exemption_type)
    admin_session.commit()

    response = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        json={
            "exemption_type_id": str(exemption_type.id),
            "start_date": str(date.today()),
            **reason_payload,
        },
        headers=auth_headers(admin),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    reason_errors = [error for error in detail if error["loc"] == ["body", "reason"]]
    assert len(reason_errors) == 1
    assert reason_errors[0]["type"] == expected_type
    assert expected_message in reason_errors[0]["msg"]
