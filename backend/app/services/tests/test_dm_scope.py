from __future__ import annotations

import uuid
import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import DutyManagerScope
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_duty_manager_scope_insert(admin_session):
    """DutyManagerScope row can be inserted and its id auto-populated."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()
    admin_session.refresh(entry)
    assert entry.id is not None


def test_duty_manager_scope_unique_constraint(admin_session):
    """Duplicate (duty_manager_id, hierarchy_node_id) raises IntegrityError."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    with pytest.raises(IntegrityError):
        admin_session.commit()
    admin_session.rollback()


def test_ranks_rasan_and_above_contents():
    from app.services.eligibility import RANKS_RASAN_AND_ABOVE
    assert RANKS_RASAN_AND_ABOVE[0] == "רסן"
    assert "סרן" not in RANKS_RASAN_AND_ABOVE
    assert "סאל" in RANKS_RASAN_AND_ABOVE
    assert "אלוף" in RANKS_RASAN_AND_ABOVE
