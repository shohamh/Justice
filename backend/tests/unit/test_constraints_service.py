import uuid
from datetime import date, timedelta

import pytest

from app.db.models import PersonalConstraint
from app.services.constraints import (
    ConstraintError,
    approve_constraint,
    cancel_constraint,
    get_approved_constraint_dates,
    list_constraints,
    reject_constraint,
    submit_constraint,
)
from tests.helpers import create_soldier


def test_submit_success(admin_session):
    s = create_soldier(admin_session, personal_number="7400001")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.commit()
    assert c.status == "pending"
    assert c.soldier_id == s.id


def test_submit_auto_approve(admin_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.constraints._get_setting_with_default",
        lambda session, key, default: False if key == "constraints.require_manager_approval" else default,
    )
    s = create_soldier(admin_session, personal_number="7400002")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=s.id,
    )
    admin_session.commit()
    assert c.status == "approved"


def test_submit_cap_enforced(admin_session):
    s = create_soldier(admin_session, personal_number="7400003")
    submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=15),
        reason="ארוך",
        actor_id=None,
    )
    admin_session.flush()
    with pytest.raises(ConstraintError, match="cap_exceeded"):
        submit_constraint(
            admin_session,
            soldier_id=s.id,
            start_date=date.today() + timedelta(days=20),
            end_date=date.today() + timedelta(days=21),
            reason="עוד",
            actor_id=None,
        )


def test_submit_bad_date_range(admin_session):
    s = create_soldier(admin_session, personal_number="7400004")
    with pytest.raises(ConstraintError, match="bad_date_range"):
        submit_constraint(
            admin_session,
            soldier_id=s.id,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 5),
            reason="no",
            actor_id=None,
        )


def test_submit_past_start(admin_session):
    s = create_soldier(admin_session, personal_number="7400005")
    with pytest.raises(ConstraintError, match="start_date_in_past"):
        submit_constraint(
            admin_session,
            soldier_id=s.id,
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 5),
            reason="past",
            actor_id=None,
        )


def test_submit_unknown_soldier(admin_session):
    with pytest.raises(ConstraintError, match="soldier_not_found"):
        submit_constraint(
            admin_session,
            soldier_id=uuid.uuid4(),
            start_date=date.today() + timedelta(days=1),
            end_date=date.today() + timedelta(days=5),
            reason="no",
            actor_id=None,
        )


def test_approve_pending(admin_session):
    s = create_soldier(admin_session, personal_number="7400006")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approved = approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.commit()
    assert approved.status == "approved"
    assert approved.decided_by == s.id


def test_approve_not_pending(admin_session):
    s = create_soldier(admin_session, personal_number="7400007")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    with pytest.raises(ConstraintError, match="not_pending"):
        approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)


def test_reject(admin_session):
    s = create_soldier(admin_session, personal_number="7400008")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    rejected = reject_constraint(admin_session, constraint_id=c.id, actor_id=s.id, decision_note="לא מתאים")
    admin_session.commit()
    assert rejected.status == "rejected"
    assert rejected.decision_note == "לא מתאים"


def test_cancel_pending(admin_session):
    s = create_soldier(admin_session, personal_number="7400009")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    c_id = c.id
    cancel_constraint(admin_session, constraint_id=c_id, actor_id=s.id)
    admin_session.commit()
    assert admin_session.get(PersonalConstraint, c_id) is None


def test_cancel_not_pending(admin_session):
    s = create_soldier(admin_session, personal_number="7400010")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    with pytest.raises(ConstraintError, match="not_pending"):
        cancel_constraint(admin_session, constraint_id=c.id, actor_id=s.id)


def test_list_constraints(admin_session):
    s = create_soldier(admin_session, personal_number="7400011")
    submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=3),
        reason="א",
        actor_id=None,
    )
    admin_session.flush()
    assert len(list_constraints(admin_session, soldier_id=s.id)) == 1


def test_get_approved_dates(admin_session):
    s = create_soldier(admin_session, personal_number="7400012")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=10),
        end_date=date.today() + timedelta(days=15),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    dates = get_approved_constraint_dates(admin_session, soldier_id=s.id)
    assert len(dates) == 1
    assert dates[0][0] == date.today() + timedelta(days=10)


def test_constraint_not_found(admin_session):
    with pytest.raises(ConstraintError, match="constraint_not_found"):
        approve_constraint(admin_session, constraint_id=uuid.uuid4(), actor_id=None)
