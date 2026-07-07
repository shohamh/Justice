from __future__ import annotations

from app.db.models import DutyLocation, HierarchyLevelType, Soldier
from app.services.import_parsers.schema import (
    ImportDutyLocationRow,
    ImportHierarchyNodeRow,
    ParsedImportData,
)
from app.services.import_sessions import _resolve_duty_locations, _resolve_hierarchy
from tests.helpers import create_node, create_soldier


def test_resolve_duty_locations_new_and_update(app_session):
    existing = DutyLocation(name="שער קיים", base="בסיס א")
    app_session.add(existing)
    app_session.flush()

    data = ParsedImportData(
        parser_id="v1_standard",
        duty_locations=[
            ImportDutyLocationRow(source_row=2, name="שער קיים", base="בסיס ב", active=True),
            ImportDutyLocationRow(source_row=3, name="שער חדש", base=None, active=None),
        ],
    )
    result = _resolve_duty_locations(app_session, data)
    assert result[0]["action"] == "update"
    assert result[0]["existing_id"] == str(existing.id)
    assert result[1]["action"] == "new"
    assert result[1]["existing_id"] is None


def test_resolve_duty_locations_missing_name_error(app_session):
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_locations=[
            ImportDutyLocationRow(source_row=2, name="", base="בסיס א", active=True),
        ],
    )
    result = _resolve_duty_locations(app_session, data)
    assert result[0]["action"] == "error"
    assert "חסר שם מיקום" in result[0]["errors"]
    assert result[0]["existing_id"] is None


def test_resolve_duty_locations_preserves_fields(app_session):
    """Verify that all fields from ImportDutyLocationRow are preserved in output."""
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_locations=[
            ImportDutyLocationRow(source_row=5, name="שער נוסף", base="בסיס ג", active=False),
        ],
    )
    result = _resolve_duty_locations(app_session, data)
    row = result[0]

    assert row["row"] == 5
    assert row["name"] == "שער נוסף"
    assert row["base"] == "בסיס ג"
    assert row["active"] is False
    assert row["action"] == "new"
    assert row["errors"] == []
    assert row["existing_id"] is None


def test_resolve_duty_locations_empty_sheet(app_session):
    """Verify handling of empty duty_locations list."""
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_locations=[],
    )
    result = _resolve_duty_locations(app_session, data)
    assert result == []


def _admin(app_session):
    return create_soldier(app_session, personal_number="admin-1", role="admin")


def test_resolve_hierarchy_parent_forward_reference(app_session):
    # "group" ranks below "unit" per the seeded HierarchyLevelType data.
    admin = _admin(app_session)
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(source_row=2, name="ילד", level="group", parent_name="הורה"),
            ImportHierarchyNodeRow(source_row=3, name="הורה", level="unit"),
        ],
    )
    result = _resolve_hierarchy(app_session, data, admin)
    child = next(r for r in result if r["name"] == "ילד")
    parent = next(r for r in result if r["name"] == "הורה")
    assert child["action"] == "new"
    assert parent["action"] == "new"
    assert child["errors"] == []


def test_resolve_hierarchy_commander_personal_number_then_name_fallback(app_session):
    admin = _admin(app_session)
    soldier = create_soldier(app_session, personal_number="12345")  # full_name = "Test 12345"
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(
                source_row=2, name="מדור א", level="group",
                commander_personal_number="not-found", commander_name="Test 12345",
            ),
        ],
    )
    result = _resolve_hierarchy(app_session, data, admin)
    assert result[0]["resolved_commander_id"] == str(soldier.id)
    assert result[0]["errors"] == []


def test_resolve_hierarchy_unresolvable_commander_is_row_error(app_session):
    admin = _admin(app_session)
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(
                source_row=2, name="מדור א", level="group",
                commander_personal_number="ghost", commander_name="לא קיים",
            ),
        ],
    )
    result = _resolve_hierarchy(app_session, data, admin)
    assert result[0]["action"] == "error"
    assert result[0]["errors"]


def test_resolve_hierarchy_duty_manager_refs_resolved(app_session):
    admin = _admin(app_session)
    dm = create_soldier(app_session, personal_number="99999")
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(
                source_row=2, name="מדור א", level="group",
                duty_manager_refs=["99999:Test 99999"],
            ),
        ],
    )
    result = _resolve_hierarchy(app_session, data, admin)
    assert result[0]["duty_manager_refs"] == [{"ref": "99999:Test 99999", "resolved_soldier_id": str(dm.id)}]


def test_resolve_hierarchy_out_of_scope_for_non_admin(app_session):
    root = create_node(app_session, level="corps", name="שורש אחר")
    dm = create_soldier(app_session, personal_number="dm-1", role="duty_manager", hierarchy_node_id=root.id)
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(source_row=2, name="מחוץ לטווח", level="corps"),
        ],
    )
    result = _resolve_hierarchy(app_session, data, dm)
    assert result[0]["action"] == "out_of_scope"


def test_resolve_hierarchy_forward_referenced_parent_is_out_of_scope_for_non_admin(app_session):
    # A non-admin's row whose parent only resolves to another *new* row later
    # in the same sheet has no real parent id yet (resolved_parent_id stays
    # None). Scope can't be verified against a parent that doesn't exist yet,
    # so this must be treated as out_of_scope for non-admins rather than
    # silently falling through to "new" with no scope check at all.
    root = create_node(app_session, level="corps", name="שורש אחר")
    dm = create_soldier(app_session, personal_number="dm-1", role="duty_manager", hierarchy_node_id=root.id)
    data = ParsedImportData(
        parser_id="v1_standard",
        hierarchy=[
            ImportHierarchyNodeRow(source_row=2, name="ילד", level="group", parent_name="הורה חדש"),
            ImportHierarchyNodeRow(source_row=3, name="הורה חדש", level="unit"),
        ],
    )
    result = _resolve_hierarchy(app_session, data, dm)
    child = next(r for r in result if r["name"] == "ילד")
    assert child["resolved_parent_id"] is None
    assert child["action"] == "out_of_scope"
