from __future__ import annotations

from app.db.models import HrHierarchySync


def test_create_hr_hierarchy_sync_defaults(admin_session):
    run = HrHierarchySync()
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.id is not None
    assert run.status == "running"
    assert run.started_at is not None
    assert run.completed_at is None
    assert run.parsed_state == []
    assert run.created_count == 0
    assert run.matched_count == 0
    assert run.held_count == 0
    assert run.error_message is None


def test_hr_hierarchy_sync_completed_state_round_trips(admin_session):
    run = HrHierarchySync(
        status="completed",
        parsed_state=[
            {
                "hr_group_id": "g1", "name": "Unit A", "action": "created",
                "resolved_node_id": None, "level": "unit", "reason": None,
            }
        ],
        created_count=1,
        matched_count=0,
        held_count=0,
    )
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.status == "completed"
    assert run.parsed_state[0]["action"] == "created"
    assert run.created_count == 1


def test_hr_hierarchy_sync_failed_state_round_trips(admin_session):
    run = HrHierarchySync(status="failed", error_message="boom")
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.status == "failed"
    assert run.error_message == "boom"
