from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models import (
    AlgorithmJob,
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    ExchangeCalendarOutbox,
)
from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_node, create_soldier


def _outbox(session, source_type: str, source_id):
    return session.scalars(
        select(ExchangeCalendarOutbox).where(
            ExchangeCalendarOutbox.source_type == source_type,
            ExchangeCalendarOutbox.source_id == source_id,
        )
    ).all()


def _manager_and_node(session, suffix: str):
    node = create_node(session, level="branch", name=f"exchange_{suffix}")
    manager = create_soldier(
        session,
        personal_number=f"exchange_{suffix}_dm",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    return manager, node


def test_bulk_accept_of_shared_shift_queues_one_shift_event(client, admin_session):
    start = date.today() + timedelta(days=20)
    manager, node = _manager_and_node(admin_session, "bulk")
    soldiers = [
        create_soldier(
            admin_session,
            personal_number=f"exchange_bulk_{index}",
            role="soldier",
            hierarchy_node_id=node.id,
        )
        for index in range(2)
    ]
    duty_type = DutyType(name="exchange_bulk_type", score_per_day=Decimal("1.00"))
    location = DutyLocation(name="exchange_bulk_location")
    admin_session.add_all([duty_type, location])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=start,
        end_date=start + timedelta(days=1),
        required_count=2,
    )
    admin_session.add(shift)
    admin_session.flush()
    job = AlgorithmJob(
        planning_start=start,
        planning_end=start + timedelta(days=1),
        shift_ids=[str(shift.id)],
        settings_json={"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 30},
        mode="shadow",
        created_by=manager.id,
    )
    admin_session.add(job)
    admin_session.flush()
    assignments = [
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            duty_shift_id=shift.id,
            algorithm_job_id=job.id,
            start_date=start,
            end_date=start + timedelta(days=1),
            status="algorithm_draft",
        )
        for soldier in soldiers
    ]
    admin_session.add_all(assignments)
    admin_session.commit()

    response = client.post(
        f"/api/algorithm/jobs/{job.id}/proposals/bulk-accept",
        json={"assignment_ids": [str(row.id) for row in assignments]},
        headers=auth_headers(manager),
    )

    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == 2
    jobs = _outbox(admin_session, "duty_shift", shift.id)
    assert len(jobs) == 1
    assert jobs[0].reason == "assignment_accepted"
    assert all(_outbox(admin_session, "duty_assignment", row.id) == [] for row in assignments)


def test_reset_published_queues_cancellation_for_assignment(client, admin_session):
    manager, node = _manager_and_node(admin_session, "reset")
    soldier = create_soldier(
        admin_session,
        personal_number="exchange_reset_soldier",
        role="soldier",
        hierarchy_node_id=node.id,
    )
    duty_type = DutyType(name="exchange_reset_type", score_per_day=Decimal("1.00"))
    location = DutyLocation(name="exchange_reset_location")
    admin_session.add_all([duty_type, location])
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date.today() + timedelta(days=60),
        end_date=date.today() + timedelta(days=60),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.commit()

    response = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 30},
        headers=auth_headers(manager),
    )

    assert response.status_code == 200, response.text
    jobs = _outbox(admin_session, "duty_assignment", assignment.id)
    assert len(jobs) == 1
    assert jobs[0].reason == "cancelled"


def test_approved_call_up_queues_original_and_replacement(client, admin_session):
    set_setting(admin_session, "forced_callup.enabled", True, actor_id=None)
    start = date.today() + timedelta(days=30)
    manager, node = _manager_and_node(admin_session, "callup")
    commander = create_soldier(
        admin_session,
        personal_number="exchange_callup_commander",
        role="commander",
        hierarchy_node_id=node.id,
    )
    node.commander_id = commander.id
    pulled = create_soldier(
        admin_session,
        personal_number="exchange_callup_pulled",
        role="soldier",
        hierarchy_node_id=node.id,
    )
    replacement = create_soldier(
        admin_session,
        personal_number="exchange_callup_replacement",
        role="soldier",
        hierarchy_node_id=node.id,
    )
    duty_type = DutyType(name="exchange_callup_type", score_per_day=Decimal("1.00"))
    location = DutyLocation(name="exchange_callup_location")
    admin_session.add_all([duty_type, location])
    admin_session.flush()
    original = DutyAssignment(
        soldier_id=pulled.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=start,
        end_date=start + timedelta(days=9),
        status="published",
    )
    admin_session.add(original)
    admin_session.commit()
    created = client.post(
        "/api/hakpaza",
        json={
            "pulled_assignment_id": str(original.id),
            "pull_date": (start + timedelta(days=4)).isoformat(),
            "replacement_soldier_id": str(replacement.id),
        },
        headers=auth_headers(commander),
    )
    assert created.status_code == 201, created.text

    approved = client.post(
        f"/api/hakpaza/{created.json()['id']}/approve",
        headers=auth_headers(manager),
    )

    assert approved.status_code == 200, approved.text
    replacement_id = approved.json()["replacement_assignment_id"]
    original_jobs = _outbox(admin_session, "duty_assignment", original.id)
    replacement_jobs = _outbox(admin_session, "duty_assignment", replacement_id)
    assert len(original_jobs) == len(replacement_jobs) == 1
    assert original_jobs[0].reason == replacement_jobs[0].reason == "call_up"
