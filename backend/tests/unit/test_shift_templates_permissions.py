"""Duty managers can now access shift-template endpoints.

This test file verifies that shift-template endpoints use Action.SHIFT_MANAGE
instead of Action.ASSIGNMENT_MANAGE, allowing duty managers (non-admin) to
access them. Previously, these endpoints gated on Action.ASSIGNMENT_MANAGE
(scope-restricted, non-DM-global) with target_node=None, which can() never
grants to a non-admin duty manager. SHIFT_MANAGE is DM-global and is the
Action the sibling shifts.py endpoints correctly use for the same pattern.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.db.models import DutyLocation, DutyType, ShiftTemplate
from tests.helpers import auth_headers, create_node, create_soldier

pytestmark = pytest.mark.duty


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_duty_manager_can_list_shift_templates(client, admin_session):
    """Duty manager (non-admin) can list shift templates."""
    # Setup: create hierarchy node, duty manager, duty type, and location
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(
        admin_session,
        personal_number=f"dm_{_uid()}",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    dt = DutyType(name=f"type_{_uid()}", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()

    # Create a shift template
    template = ShiftTemplate(
        name=f"template_{_uid()}",
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        recurrence_type="weekly",
        weekdays=[1, 3, 5],
        duration_days=1,
        start_time="08:00",
        end_time="17:00",
        required_count=1,
        active=True,
    )
    admin_session.add(template)
    admin_session.commit()

    # Test: duty manager can list templates
    resp = client.get("/api/shift-templates", headers=auth_headers(dm))
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(t["id"] == str(template.id) for t in data)


def test_duty_manager_can_create_shift_template(client, admin_session):
    """Duty manager (non-admin) can create shift templates."""
    # Setup: create hierarchy node, duty manager, duty type, and location
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(
        admin_session,
        personal_number=f"dm_{_uid()}",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    dt = DutyType(name=f"type_{_uid()}", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.commit()

    # Test: duty manager can create template
    template_name = f"new_template_{_uid()}"
    resp = client.post(
        "/api/shift-templates",
        json={
            "name": template_name,
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "recurrence_type": "weekly",
            "weekdays": [1, 3, 5],
            "duration_days": 1,
            "start_time": "08:00",
            "end_time": "17:00",
            "required_count": 1,
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert data["name"] == template_name


def test_duty_manager_can_update_shift_template(client, admin_session):
    """Duty manager (non-admin) can update shift templates."""
    # Setup: create hierarchy node, duty manager, duty type, location, and template
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(
        admin_session,
        personal_number=f"dm_{_uid()}",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    dt = DutyType(name=f"type_{_uid()}", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()

    template = ShiftTemplate(
        name=f"template_{_uid()}",
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        recurrence_type="weekly",
        weekdays=[1, 3, 5],
        duration_days=1,
        start_time="08:00",
        end_time="17:00",
        required_count=1,
        active=True,
    )
    admin_session.add(template)
    admin_session.commit()

    # Test: duty manager can update template
    new_name = f"updated_template_{_uid()}"
    resp = client.patch(
        f"/api/shift-templates/{template.id}",
        json={"name": new_name},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert data["name"] == new_name


def test_duty_manager_can_delete_shift_template(client, admin_session):
    """Duty manager (non-admin) can delete shift templates."""
    # Setup: create hierarchy node, duty manager, duty type, location, and template
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(
        admin_session,
        personal_number=f"dm_{_uid()}",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    dt = DutyType(name=f"type_{_uid()}", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()

    template = ShiftTemplate(
        name=f"template_{_uid()}",
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        recurrence_type="weekly",
        weekdays=[1, 3, 5],
        duration_days=1,
        start_time="08:00",
        end_time="17:00",
        required_count=1,
        active=True,
    )
    admin_session.add(template)
    admin_session.commit()

    # Test: duty manager can delete template
    resp = client.delete(
        f"/api/shift-templates/{template.id}",
        headers=auth_headers(dm),
    )
    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.json()}"


def test_duty_manager_can_preview_shift_template(client, admin_session):
    """Duty manager (non-admin) can preview shift template generation."""
    # Setup: create hierarchy node, duty manager, duty type, location, and template
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(
        admin_session,
        personal_number=f"dm_{_uid()}",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    dt = DutyType(name=f"type_{_uid()}", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()

    template = ShiftTemplate(
        name=f"template_{_uid()}",
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        recurrence_type="weekly",
        weekdays=[1, 3, 5],
        duration_days=1,
        start_time="08:00",
        end_time="17:00",
        required_count=1,
        active=True,
    )
    admin_session.add(template)
    admin_session.commit()

    # Test: duty manager can preview template
    resp = client.post(
        f"/api/shift-templates/{template.id}/preview",
        json={"range_start": "2026-08-01", "range_end": "2026-08-31"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert isinstance(data, list)


def test_duty_manager_can_generate_shifts_from_template(client, admin_session):
    """Duty manager (non-admin) can generate shifts from a template."""
    # Setup: create hierarchy node, duty manager, duty type, location, and template
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(
        admin_session,
        personal_number=f"dm_{_uid()}",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    dt = DutyType(name=f"type_{_uid()}", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()

    template = ShiftTemplate(
        name=f"template_{_uid()}",
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        recurrence_type="weekly",
        weekdays=[1, 3, 5],
        duration_days=1,
        start_time="08:00",
        end_time="17:00",
        required_count=1,
        active=True,
    )
    admin_session.add(template)
    admin_session.commit()

    # Test: duty manager can generate shifts
    resp = client.post(
        f"/api/shift-templates/{template.id}/generate",
        json={"range_start": "2026-08-01", "range_end": "2026-08-31"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert "created_count" in data
