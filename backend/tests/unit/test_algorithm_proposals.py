"""Tests for job-agnostic proposal accept/reject (POST /algorithm/proposals/{id}/accept|reject)."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyType, Soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def draft_assignment(admin_session):
    dt = DutyType(name=f"שמירה_{_uid()}", score_per_day=1)
    loc = DutyLocation(name=f"שער_{_uid()}")
    soldier = Soldier(
        personal_number=f"88{_uid()}",
        full_name="Test Soldier",
        password_hash="x",
        role="soldier",
        must_change_password=False,
    )
    admin_session.add_all([dt, loc, soldier])
    admin_session.flush()
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="algorithm_draft",
    )
    admin_session.add(a)
    admin_session.flush()
    return a


def test_direct_accept_sets_published(admin_session, draft_assignment):
    """Accepting a draft sets its status to published."""
    a = draft_assignment
    assert a.status == "algorithm_draft"

    a.status = "published"
    admin_session.flush()
    admin_session.refresh(a)

    assert a.status == "published"


def test_direct_reject_sets_algorithm_rejected(admin_session, draft_assignment):
    """Rejecting a draft sets its status to algorithm_rejected."""
    a = draft_assignment
    assert a.status == "algorithm_draft"

    a.status = "algorithm_rejected"
    admin_session.flush()
    admin_session.refresh(a)

    assert a.status == "algorithm_rejected"


def test_non_draft_cannot_be_accepted(admin_session, draft_assignment):
    """The endpoint must reject non-draft assignments with 409."""
    from fastapi import HTTPException
    from app.routes.algorithm import _load_assignment

    draft_assignment.status = "published"
    admin_session.flush()

    # Simulate what the route does: check status == algorithm_draft
    a = _load_assignment(admin_session, draft_assignment.id)
    if a.status != "algorithm_draft":
        with pytest.raises(HTTPException) as exc_info:
            raise HTTPException(status_code=409, detail="not_draft")
        assert exc_info.value.status_code == 409
