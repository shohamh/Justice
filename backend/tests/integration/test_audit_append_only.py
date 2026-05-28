import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.audit.writer import write_audit


def test_app_role_can_insert_into_audit_log(app_session):
    write_audit(
        app_session,
        actor_id=None,
        action="test.action",
        entity_type="test",
        entity_id=uuid.uuid4(),
        after={"hello": "world"},
    )
    app_session.commit()
    row = app_session.execute(
        text("SELECT action FROM audit_log ORDER BY created_at DESC LIMIT 1")
    ).first()
    assert row is not None
    assert row[0] == "test.action"


def test_app_role_cannot_update_audit_log(app_session):
    write_audit(
        app_session,
        actor_id=None,
        action="will.be.attacked",
        entity_type="test",
        entity_id=uuid.uuid4(),
    )
    app_session.commit()
    with pytest.raises(ProgrammingError) as exc:
        app_session.execute(
            text("UPDATE audit_log SET action='tampered' WHERE action='will.be.attacked'")
        )
        app_session.commit()
    assert "permission denied" in str(exc.value).lower()


def test_app_role_cannot_delete_from_audit_log(app_session):
    write_audit(
        app_session,
        actor_id=None,
        action="will.be.deleted",
        entity_type="test",
        entity_id=uuid.uuid4(),
    )
    app_session.commit()
    with pytest.raises(ProgrammingError) as exc:
        app_session.execute(text("DELETE FROM audit_log WHERE action='will.be.deleted'"))
        app_session.commit()
    assert "permission denied" in str(exc.value).lower()
