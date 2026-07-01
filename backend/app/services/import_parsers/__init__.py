"""Plugin pattern for parsing externally-produced Excel workbooks into a common schema.

Each supported spreadsheet layout is implemented as a class satisfying the
`ImportParser` protocol (`id`, `label`, `detect`, `parse`) and registered with
`registry.register()`. Callers who don't know which layout they're dealing with
can hand a workbook to `registry.auto_detect_parser()`, which asks every
registered parser for a confidence score via `detect()` and returns the
best-scoring match above its threshold. This keeps the "which spreadsheet
layout is this" concern isolated per-parser, so adding support for a new
layout never requires touching existing parsers or the calling code.
"""

from __future__ import annotations

from typing import Protocol

import openpyxl

from app.services.import_parsers.schema import ParsedImportData


class ImportParser(Protocol):
    id: str
    label: str

    def detect(self, wb: openpyxl.Workbook) -> float:
        """Score how confident this parser is that `wb` matches its layout.

        Returns a float from 0.0 (no match) to 1.0 (certain match).
        `registry.auto_detect_parser()` calls this on every registered parser
        and picks the highest-scoring one, provided it clears its threshold.
        """
        ...

    def parse(self, wb: openpyxl.Workbook) -> ParsedImportData:
        """Fully parse `wb` into a `ParsedImportData`.

        Every row produced must set `source_row` to the original spreadsheet
        row number so validation/import errors can be traced back to the
        exact row the user needs to fix.
        """
        ...
