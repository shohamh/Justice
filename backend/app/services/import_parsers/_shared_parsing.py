from __future__ import annotations

from datetime import date as date_type
from typing import Any

"""Shared cell-parsing helpers used across import parsers (v1_standard and the
legacy app/routes/import_excel.py endpoints). Kept small and dependency-free
so it can be imported from either place without pulling in DB/route code.
"""


def parse_date(val: Any) -> str | None:
    """Accept dd.mm.yyyy or yyyy-mm-dd strings, or date objects."""
    if val is None:
        return None
    if isinstance(val, date_type):
        return val.isoformat()
    s = str(val).strip()
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        d, m, y = s.split(".")
        return f"{y}-{m}-{d}"
    return s  # assume ISO


def parse_bool(val: Any) -> bool | None:
    if val is None:
        return None
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "כן", "נכון")
