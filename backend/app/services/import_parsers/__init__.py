from __future__ import annotations

from typing import Protocol

import openpyxl

from app.services.import_parsers.schema import ParsedImportData


class ImportParser(Protocol):
    id: str
    label: str

    def detect(self, wb: openpyxl.Workbook) -> float: ...
    def parse(self, wb: openpyxl.Workbook) -> ParsedImportData: ...
