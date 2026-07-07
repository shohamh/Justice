from __future__ import annotations

from typing import Any

import openpyxl

from app.services.import_parsers._shared_parsing import parse_bool as _parse_bool
from app.services.import_parsers._shared_parsing import parse_date as _parse_date
from app.services.import_parsers.registry import register
from app.services.import_parsers.schema import (
    ImportAssignmentRow,
    ImportDutyShiftRow,
    ImportNodeQuota,
    ImportSoldierRow,
    ParsedImportData,
)

KNOWN_SHEETS = {"soldiers", "duty_shifts", "assignments"}


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


def _parse_node_quotas(raw: Any, source_row: int) -> tuple[list[ImportNodeQuota], list[str]]:
    """Parse the new `node_quotas` column: "node_name:count;node_name:count".

    Malformed entries (missing colon, or a non-integer count) are skipped
    individually rather than crashing the whole import or vanishing silently;
    each produces a row-tagged warning string.
    """
    s = str(raw or "").strip()
    if not s:
        return [], []
    quotas: list[ImportNodeQuota] = []
    warnings: list[str] = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            warnings.append(
                f"שורה {source_row}: ערך מכסה שגוי '{part}' — הפורמט הנדרש הוא 'שם_יחידה:כמות'"
            )
            continue
        name, count_s = part.rsplit(":", 1)
        try:
            count = int(count_s.strip())
        except ValueError:
            warnings.append(
                f"שורה {source_row}: ערך מכסה שגוי '{part}' — הפורמט הנדרש הוא 'שם_יחידה:כמות'"
            )
            continue
        quotas.append(ImportNodeQuota(node_name=name.strip(), count=count))
    return quotas, warnings


class V1StandardParser:
    """Standard v1 layout: `soldiers`, `duty_shifts`, `assignments`.

    Shift templates are not importable via Excel — they're managed only
    through the system UI. A `shift_templates` sheet, if present, is ignored.
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

        duty_shifts = []
        for r in _sheet_rows(wb, "duty_shifts"):
            node_quotas, node_quota_warnings = _parse_node_quotas(r.get("node_quotas"), r["_row"])
            warnings.extend(node_quota_warnings)
            duty_shifts.append(
                ImportDutyShiftRow(
                    source_row=r["_row"],
                    duty_type_name=str(r.get("duty_type_name") or "").strip(),
                    duty_location_name=str(r.get("duty_location_name") or "").strip(),
                    start_date=_parse_date(r.get("start_date")) or "",
                    end_date=_parse_date(r.get("end_date")) or "",
                    start_time=str(r.get("start_time") or "").strip() or None,
                    end_time=str(r.get("end_time") or "").strip() or None,
                    required_count=int(r.get("required_count") or 1),
                    node_quotas=node_quotas,
                    notes=str(r.get("notes") or "").strip() or None,
                )
            )

        assignments = [
            ImportAssignmentRow(
                source_row=r["_row"],
                personal_number=str(r.get("personal_number") or "").strip(),
                full_name=str(r.get("full_name") or "").strip(),
                duty_type_name=str(r.get("duty_type_name") or "").strip(),
                duty_location_name=str(r.get("duty_location_name") or "").strip(),
                start_date=_parse_date(r.get("start_date")) or "",
                end_date=_parse_date(r.get("end_date")) or "",
                start_time=str(r.get("start_time") or "").strip() or None,
                end_time=str(r.get("end_time") or "").strip() or None,
                is_reserve=_parse_bool(r.get("is_reserve")) or False,
                notes=str(r.get("notes") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "assignments")
        ]

        return ParsedImportData(
            soldiers=soldiers,
            duty_shifts=duty_shifts,
            assignments=assignments,
            parser_id=self.id,
            parser_warnings=warnings,
        )


register(V1StandardParser())
