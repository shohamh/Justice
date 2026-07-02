from __future__ import annotations

import openpyxl

from app.services.import_parsers import ImportParser

PARSER_REGISTRY: dict[str, ImportParser] = {}


def register(parser: ImportParser) -> None:
    if parser.id in PARSER_REGISTRY:
        raise ValueError(f"parser id '{parser.id}' is already registered")
    PARSER_REGISTRY[parser.id] = parser


def auto_detect_parser(wb: openpyxl.Workbook, threshold: float = 0.5) -> ImportParser:
    best: tuple[float, ImportParser | None] = (0.0, None)
    for parser in PARSER_REGISTRY.values():
        score = parser.detect(wb)
        # Strict `>` means ties keep the first-registered parser (dict insertion order).
        if score > best[0]:
            best = (score, parser)
    if best[1] is None or best[0] < threshold:
        raise ValueError("פורמט קובץ אקסל לא מזוהה — לא נמצאה תבנית תואמת")
    return best[1]


def get_parser(parser_id: str) -> ImportParser:
    parser = PARSER_REGISTRY.get(parser_id)
    if parser is None:
        raise ValueError(f"unknown parser_id: {parser_id}")
    return parser
