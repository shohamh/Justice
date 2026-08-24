from __future__ import annotations

from pydantic import BaseModel


class ImportNodeQuota(BaseModel):
    node_name: str
    count: int


class ImportSoldierRow(BaseModel):
    source_row: int
    personal_number: str
    full_name: str
    rank: str | None = None
    gender: str | None = None
    is_officer: bool | None = None
    hierarchy_node_name: str | None = None
    enrolled_at: str | None = None
    enlistment_date: str | None = None
    phone: str | None = None
    email: str | None = None
    is_career: bool | None = None
    next_rank_date: str | None = None
    bahad1_graduate: bool | None = None
    rank_track: str | None = None
    has_military_driving_license: bool | None = None
    military_driving_license_expiry: str | None = None
    mandatory_end_date: str | None = None
    discharge_date: str | None = None
    last_mitvahim_date: str | None = None
    last_alal_date: str | None = None
    left_at: str | None = None


class ImportDutyShiftRow(BaseModel):
    source_row: int
    duty_type_name: str
    duty_location_name: str
    start_date: str
    end_date: str
    start_time: str | None = None
    end_time: str | None = None
    required_count: int
    reserve_count_override: int | None = None
    node_quotas: list[ImportNodeQuota] = []
    notes: str | None = None


class ImportDutyLocationRow(BaseModel):
    source_row: int
    name: str
    base: str | None = None
    active: bool | None = None


class ImportHierarchyNodeRow(BaseModel):
    source_row: int
    name: str
    level: str
    parent_name: str | None = None
    commander_personal_number: str | None = None
    commander_name: str | None = None
    duty_manager_refs: list[str] = []


class ImportDutyTypeRow(BaseModel):
    source_row: int
    name: str
    score_per_day: str
    description: str | None = None
    active: bool | None = None
    reserve_ratio: str | None = None
    reserve_minimum: int | None = None
    is_external: bool | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    instructions: str | None = None
    eligible_unit_names: list[str] = []
    requires_weapon: bool | None = None
    required_range_type: str | None = None
    requirements_json: str | None = None


class ImportShiftTemplateRow(BaseModel):
    source_row: int
    name: str
    duty_type_name: str
    duty_location_name: str
    recurrence_type: str | None = None
    weekdays: list[int] = []
    start_time: str | None = None
    end_time: str | None = None
    required_count: int | None = None
    auto_roll: bool | None = None
    auto_roll_until: str | None = None
    active: bool | None = None
    duration_days: int | None = None
    notes: str | None = None
    eligible_unit_names: list[str] = []


class ImportExemptionTypeRow(BaseModel):
    source_row: int
    name: str
    description: str | None = None
    is_global: bool | None = None
    is_medical: bool | None = None
    is_commander_exemption: bool | None = None
    active: bool | None = None
    forbids_weapons: bool | None = None
    applies_to_duty_type_names: list[str] = []


class ImportAssignmentRow(BaseModel):
    source_row: int
    personal_number: str
    full_name: str
    duty_type_name: str
    duty_location_name: str
    start_date: str
    end_date: str
    start_time: str | None = None
    end_time: str | None = None
    is_reserve: bool = False
    notes: str | None = None


class ImportRangeLocationRow(BaseModel):
    source_row: int
    name: str
    active: bool | None = None


class ImportRangeEventRow(BaseModel):
    source_row: int
    hierarchy_node_name: str | None = None
    range_type: str
    date: str
    range_location_name: str
    required_count: int
    reserve_count: int = 0
    start_time: str | None = None
    end_time: str | None = None
    arrival_instructions: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    status: str | None = None


class ImportRangeAssignmentRow(BaseModel):
    source_row: int
    personal_number: str
    full_name: str
    hierarchy_node_name: str | None = None
    range_type: str
    date: str
    range_location_name: str
    is_reserve: bool = False
    is_draft: bool = False
    attendance_status: str | None = None
    note: str | None = None


class ImportSoldierRangeQualificationRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    range_type: str
    valid_until: str


class ImportRangeExcusalRequestRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    requested_by_personal_number: str | None = None
    hierarchy_node_name: str | None = None
    range_type: str
    date: str
    range_location_name: str
    reason: str | None = None
    status: str
    decided_by_personal_number: str | None = None
    decision_note: str | None = None


class ImportSwapRequestRow(BaseModel):
    source_row: int
    id: str | None = None
    requesting_personal_number: str
    target_personal_number: str | None = None
    covering_personal_number: str | None = None
    duty_date: str
    status: str
    reason: str | None = None
    requester_side_approved: bool | None = None
    covering_side_approved: bool | None = None
    rejected_by_personal_number: str | None = None
    decision_note: str | None = None
    approval_log: str | None = None  # "side:kind:person_pn:approved|rejected:iso_datetime;..."


class ImportExemptionRequestRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    exemption_type_name: str
    start_date: str
    end_date: str | None = None
    reason: str | None = None
    status: str
    commander_approved_by_personal_number: str | None = None
    decided_by_personal_number: str | None = None
    decision_note: str | None = None
    files: str | None = None  # flattened filenames, comma-separated


class ImportSoldierFieldUpdateRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    field_name: str
    new_value: str
    previous_value: str | None = None
    status: str
    decided_by_personal_number: str | None = None
    decision_note: str | None = None


class ImportSoldierEnrollmentRequestRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    requested_node_name: str
    status: str
    decided_by_personal_number: str | None = None
    decision_note: str | None = None


class ImportPersonalConstraintRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    start_date: str
    end_date: str
    reason: str | None = None
    status: str
    decided_by_personal_number: str | None = None
    decision_note: str | None = None


class ImportSoldierExemptionRow(BaseModel):
    source_row: int
    id: str | None = None
    soldier_personal_number: str
    exemption_type_name: str
    start_date: str
    end_date: str | None = None
    reason: str | None = None
    granted_by_personal_number: str | None = None
    revoked: bool = False
    revoke_reason: str | None = None


class ImportSystemSettingRow(BaseModel):
    source_row: int
    key: str
    value_json: str


class ImportBugReportRow(BaseModel):
    source_row: int
    id: str | None = None
    reporter_personal_number: str
    description: str
    severity: str
    route: str
    status: str
    created_at: str | None = None
    nav_history_json: str | None = None
    audit_snapshot_json: str | None = None
    user_snapshot_json: str | None = None


class ImportRankAdvancementIntervalRow(BaseModel):
    source_row: int
    track: str
    rank: str
    months_to_next: int
    advance_on_career_entry: bool | None = None


class ParsedImportData(BaseModel):
    """Canonical output every import parser implementation must produce.

    This decouples "reading a particular Excel layout" (each `ImportParser`)
    from "validating/applying rows" (the import route/service layer), so new
    spreadsheet layouts can be supported by adding a parser without changing
    how imported data is validated or applied.

    """

    soldiers: list[ImportSoldierRow] = []
    duty_shifts: list[ImportDutyShiftRow] = []
    duty_locations: list[ImportDutyLocationRow] = []
    hierarchy: list[ImportHierarchyNodeRow] = []
    duty_types: list[ImportDutyTypeRow] = []
    shift_templates: list[ImportShiftTemplateRow] = []
    exemption_types: list[ImportExemptionTypeRow] = []
    assignments: list[ImportAssignmentRow] = []
    range_locations: list[ImportRangeLocationRow] = []
    range_events: list[ImportRangeEventRow] = []
    range_assignments: list[ImportRangeAssignmentRow] = []
    soldier_range_qualifications: list[ImportSoldierRangeQualificationRow] = []
    range_excusal_requests: list[ImportRangeExcusalRequestRow] = []
    swap_requests: list[ImportSwapRequestRow] = []
    exemption_requests: list[ImportExemptionRequestRow] = []
    soldier_field_updates: list[ImportSoldierFieldUpdateRow] = []
    soldier_enrollment_requests: list[ImportSoldierEnrollmentRequestRow] = []
    personal_constraints: list[ImportPersonalConstraintRow] = []
    soldier_exemptions: list[ImportSoldierExemptionRow] = []
    system_settings: list[ImportSystemSettingRow] = []
    bug_reports: list[ImportBugReportRow] = []
    parser_id: str
    rank_advancement_intervals: list[ImportRankAdvancementIntervalRow] = []
    parser_warnings: list[str] = []
