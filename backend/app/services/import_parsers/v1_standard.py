from __future__ import annotations

from datetime import date as date_type
from typing import Any

import openpyxl

from app.services.import_parsers.registry import register
from app.services.import_parsers.schema import (
    ImportDutyShiftRow,
    ImportNodeQuota,
    ImportShiftTemplateRow,
    ImportSoldierRow,
    ParsedImportData,
)

KNOWN_SHEETS = {"soldiers", "duty_shifts", "shift_templates", "assignments"}


def _parse_date(val: Any) -> str | None:
    """Accept dd.mm.yyyy or yyyy-mm-dd strings, or date objects.

    Ported from app/routes/import_excel.py's `_parse_date` helper.
    """
    if val is None:
        return None
    if isinstance(val, date_type):
        return val.isoformat()
    s = str(val).strip()
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        d, m, y = s.split(".")
        return f"{y}-{m}-{d}"
    return s  # assume ISO


def _parse_bool(val: Any) -> bool | None:
    """Ported from app/routes/import_excel.py's `_parse_bool` helper."""
    if val is None:
        return None
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "כן", "נכון")


def _sheet_rows(wb: openpyxl.Workbook, name: str) -> list[dict[str, Any]]:
    """Read a sheet's rows as dicts keyed by lowercased header, skipping blank rows.

    Ported convention from app/routes/import_excel.py's per-sheet parsers:
    header row lowercased, data starts at row 2, all-None rows are skipped.
    """
    if name not in wb.sheetnames:
        return []
    ws = wb[name]
    headers = [str(c.value).strip().lower() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    out = []
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if all(v is None for v in row):
            continue
        out.append({"_row": i, **dict(zip(headers, row))})
    return out


def _parse_node_quotas(raw: Any) -> list[ImportNodeQuota]:
    """Parse the new `node_quotas` column: "node_name:count;node_name:count"."""
    s = str(raw or "").strip()
    if not s:
        return []
    quotas = []
    for part in s.split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, count_s = part.rsplit(":", 1)
        quotas.append(ImportNodeQuota(node_name=name.strip(), count=int(count_s.strip())))
    return quotas


class V1StandardParser:
    """Standard v1 layout: `soldiers`, `duty_shifts` (primary), `shift_templates`.

    Also accepts the legacy `assignments` sheet as a fallback source for
    duty shifts when no `duty_shifts` sheet is present, converting each
    assignment row (which has no `required_count`) into a duty shift row
    with `required_count=1`.
    """

    id = "v1_standard"
    label = "תבנית סטנדרטית (v1)"

    def detect(self, wb: openpyxl.Workbook) -> float:
        matches = KNOWN_SHEETS & set(wb.sheetnames)
        if not matches:
            return 0.0
        return min(1.0, 0.5 + 0.2 * len(matches))

    def parse(self, wb: openpyxl.Workbook) -> ParsedImportData:
        warnings: list[str] = []

        soldiers = [
            ImportSoldierRow(
                source_row=r["_row"],
                personal_number=str(r.get("personal_number") or "").strip(),
                full_name=str(r.get("full_name") or "").strip(),
                rank=str(r.get("rank") or "").strip() or None,
                gender=str(r.get("gender") or "").strip() or None,
                is_officer=_parse_bool(r.get("is_officer")),
                hierarchy_node_name=str(r.get("hierarchy_node_name") or "").strip() or None,
                enrolled_at=_parse_date(r.get("enrolled_at")),
                enlistment_date=_parse_date(r.get("enlistment_date")),
                phone=str(r.get("phone") or "").strip() or None,
                email=str(r.get("email") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "soldiers")
        ]

        duty_shift_rows = _sheet_rows(wb, "duty_shifts")
        if not duty_shift_rows and "assignments" in wb.sheetnames:
            warnings.append(
                "no 'duty_shifts' sheet found — falling back to legacy 'assignments' sheet "
                "(required_count defaulted to 1 per row, no node_quotas support)"
            )
            for r in _sheet_rows(wb, "assignments"):
                duty_shift_rows.append({
                    "_row": r["_row"],
                    "duty_type_name": r.get("duty_type_name"),
                    "duty_location_name": None,
                    "start_date": r.get("start_date"),
                    "end_date": r.get("end_date"),
                    "required_count": 1,
                    "node_quotas": None,
                    "notes": None,
                })

        duty_shifts = [
            ImportDutyShiftRow(
                source_row=r["_row"],
                duty_type_name=str(r.get("duty_type_name") or "").strip(),
                duty_location_name=str(r.get("duty_location_name") or "").strip(),
                start_date=_parse_date(r.get("start_date")) or "",
                end_date=_parse_date(r.get("end_date")) or "",
                start_time=str(r.get("start_time") or "").strip() or None,
                end_time=str(r.get("end_time") or "").strip() or None,
                required_count=int(r.get("required_count") or 1),
                node_quotas=_parse_node_quotas(r.get("node_quotas")),
                notes=str(r.get("notes") or "").strip() or None,
            )
            for r in duty_shift_rows
        ]

        shift_templates = [
            ImportShiftTemplateRow(
                source_row=r["_row"],
                name=str(r.get("name") or "").strip(),
                duty_type_name=str(r.get("duty_type_name") or "").strip(),
                # ISO weekday numbering (Mon=1...Sun=7), matching
                # app/services/shift_templates.py — source data is expected
                # to already use this convention (no transformation applied
                # here, same as the legacy _parse_templates_sheet).
                days_of_week=[int(d.strip()) for d in str(r.get("days_of_week") or "").split(",") if d.strip()],
                required_primary=int(r.get("required_primary") or 1),
                required_reserve=int(r.get("required_reserve") or 0),
            )
            for r in _sheet_rows(wb, "shift_templates")
        ]

        return ParsedImportData(
            soldiers=soldiers,
            duty_shifts=duty_shifts,
            shift_templates=shift_templates,
            parser_id=self.id,
            parser_warnings=warnings,
        )


register(V1StandardParser())
