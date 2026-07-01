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


class ImportDutyShiftRow(BaseModel):
    source_row: int
    duty_type_name: str
    duty_location_name: str
    start_date: str
    end_date: str
    start_time: str | None = None
    end_time: str | None = None
    required_count: int
    node_quotas: list[ImportNodeQuota] = []
    notes: str | None = None


class ImportShiftTemplateRow(BaseModel):
    source_row: int
    name: str
    duty_type_name: str
    # ISO weekday numbering used throughout this codebase: Mon=1 ... Sun=7
    # (matches date.isoweekday(), see app/services/shift_templates.py).
    days_of_week: list[int]
    required_primary: int
    required_reserve: int = 0


class ParsedImportData(BaseModel):
    """Canonical output every import parser implementation must produce.

    This decouples "reading a particular Excel layout" (each `ImportParser`)
    from "validating/applying rows" (the import route/service layer), so new
    spreadsheet layouts can be supported by adding a parser without changing
    how imported data is validated or applied.
    """

    soldiers: list[ImportSoldierRow] = []
    duty_shifts: list[ImportDutyShiftRow] = []
    shift_templates: list[ImportShiftTemplateRow] = []
    parser_id: str
    parser_warnings: list[str] = []
