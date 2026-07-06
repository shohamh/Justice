from __future__ import annotations

from typing import Any

import openpyxl

from app.services.import_parsers._shared_parsing import parse_bool as _parse_bool
from app.services.import_parsers._shared_parsing import parse_date as _parse_date
from app.services.import_parsers.registry import register
from app.services.import_parsers.schema import (
    ImportDutyLocationRow,
    ImportDutyShiftRow,
    ImportExemptionTypeRow,
    ImportNodeQuota,
    ImportSoldierRow,
    ParsedImportData,
)

KNOWN_SHEETS = {"soldiers", "duty_shifts", "assignments", "duty_locations", "exemption_types"}


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


def _parse_name_list(raw: Any) -> list[str]:
    """Parse a comma-separated list of names, stripping whitespace.

    Used for applies_to_duty_type_names, eligible_unit_names, etc.
    Empty cell or whitespace-only cell returns empty list.
    """
    s = str(raw or "").strip()
    if not s:
        return []
    return [name.strip() for name in s.split(",") if name.strip()]


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
    """Standard v1 layout: `soldiers`, `duty_shifts` (primary).

    Shift templates are not importable via Excel — they're managed only
    through the system UI. A `shift_templates` sheet, if present, is ignored.

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
                "לא נמצא גיליון 'duty_shifts' — נעשה שימוש בגיליון הישן 'assignments' "
                "(הכמות הנדרשת הוגדרה כברירת מחדל 1 לשורה, ללא תמיכה במכסות יחידה)"
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

        duty_shifts = []
        for r in duty_shift_rows:
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

        duty_locations = [
            ImportDutyLocationRow(
                source_row=r["_row"],
                name=str(r.get("name") or "").strip(),
                base=str(r.get("base") or "").strip() or None,
                active=_parse_bool(r.get("active")),
            )
            for r in _sheet_rows(wb, "duty_locations")
        ]

        exemption_types = [
            ImportExemptionTypeRow(
                source_row=r["_row"],
                name=str(r.get("name") or "").strip(),
                description=str(r.get("description") or "").strip() or None,
                is_global=_parse_bool(r.get("is_global")),
                is_medical=_parse_bool(r.get("is_medical")),
                is_commander_exemption=_parse_bool(r.get("is_commander_exemption")),
                applies_to_duty_type_names=_parse_name_list(r.get("applies_to_duty_types")),
            )
            for r in _sheet_rows(wb, "exemption_types")
        ]

        return ParsedImportData(
            soldiers=soldiers,
            duty_shifts=duty_shifts,
            duty_locations=duty_locations,
            exemption_types=exemption_types,
            parser_id=self.id,
            parser_warnings=warnings,
        )


register(V1StandardParser())
