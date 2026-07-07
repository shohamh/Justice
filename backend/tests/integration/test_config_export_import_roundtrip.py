from __future__ import annotations

import uuid
from decimal import Decimal

from app.db.models import DutyLocation
from app.services.duty_config import create_duty_type, create_exemption_type, set_exemption_duty_types
from app.services.hierarchy import create_node, set_commander
from tests.helpers import auth_headers, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _token(soldier) -> str:
    return auth_headers(soldier)["Authorization"].split(" ", 1)[1]


def test_export_then_reimport_resolves_everything_as_update(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    commander = create_soldier(admin_session, personal_number=f"cmd_{_uid()}")
    node = create_node(admin_session, level="group", name=f"מדור_{_uid()}", parent_id=None)
    set_commander(admin_session, node_id=node.id, commander_id=commander.id, actor_id=admin.id)
    loc = DutyLocation(name=f"שער_{_uid()}", base="בסיס א")
    admin_session.add(loc)
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    et = create_exemption_type(admin_session, name=f"et_{_uid()}")
    set_exemption_duty_types(admin_session, exemption_type_id=et.id, duty_type_ids=[dt.id])
    admin_session.commit()

    export_resp = client.get(
        "/api/config/export", headers={"Authorization": f"Bearer {_token(admin)}"}
    )
    assert export_resp.status_code == 200

    upload_resp = client.post(
        "/api/import/sessions?parser_id=v1_standard",
        files={"file": ("export.xlsx", export_resp.content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert upload_resp.status_code == 200
    preview = upload_resp.json()["preview"]

    for group in ("duty_locations", "hierarchy", "duty_types", "exemption_types"):
        for row in preview[group]:
            assert row["action"] == "update", f"{group} row {row['row']} expected update, got {row['action']}: {row['errors']}"
