from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.db.models import PersonalConstraint, PersonalConstraintOverride, Soldier


def _make_soldier(session):
    """Helper to create a test soldier."""
    s = Soldier(
        personal_number=str(uuid.uuid4())[:8],
        full_name="Test Soldier",
        password_hash="x",
    )
    session.add(s)
    session.flush()
    return s


def test_personal_constraint_override_round_trips(app_session):
    soldier: Soldier = _make_soldier(app_session)
    overridden_by: Soldier = _make_soldier(app_session)
    constraint = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=1),
        reason="בקשה אישית",
        status="approved",
    )
    app_session.add(constraint)
    app_session.flush()

    override = PersonalConstraintOverride(
        personal_constraint_id=constraint.id,
        soldier_id=soldier.id,
        overridden_by=overridden_by.id,
        assignment_kind="duty",
        reference_id=uuid.uuid4(),
        reason="צורך מבצעי דחוף",
    )
    app_session.add(override)
    app_session.flush()
    app_session.refresh(override)

    assert override.id is not None
    assert override.overridden_at is not None
    assert override.personal_constraint_id == constraint.id
    assert override.assignment_kind == "duty"
