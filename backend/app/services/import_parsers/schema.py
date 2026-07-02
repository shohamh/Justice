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


class ParsedImportData(BaseModel):
    """Canonical output every import parser implementation must produce.

    This decouples "reading a particular Excel layout" (each `ImportParser`)
    from "validating/applying rows" (the import route/service layer), so new
    spreadsheet layouts can be supported by adding a parser without changing
    how imported data is validated or applied.

    Shift templates are intentionally not importable via Excel — they're
    created and managed only through the system UI (see
    app/routes/shift_templates.py).
    """

    soldiers: list[ImportSoldierRow] = []
    duty_shifts: list[ImportDutyShiftRow] = []
    parser_id: str
    parser_warnings: list[str] = []
