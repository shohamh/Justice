import openpyxl
import pytest

from app.services.import_parsers.registry import PARSER_REGISTRY, auto_detect_parser, register
from app.services.import_parsers.schema import ParsedImportData


class _FakeParser:
    id = "fake"
    label = "Fake Parser"

    def detect(self, wb):
        return 0.9

    def parse(self, wb):
        return ParsedImportData(soldiers=[], duty_shifts=[], parser_id=self.id)


def test_auto_detect_picks_highest_confidence():
    PARSER_REGISTRY["fake"] = _FakeParser()
    try:
        wb = openpyxl.Workbook()
        parser = auto_detect_parser(wb)
        assert parser.id == "fake"
    finally:
        del PARSER_REGISTRY["fake"]


def test_auto_detect_raises_when_no_match():
    wb = openpyxl.Workbook()
    with pytest.raises(ValueError, match="לא מזוהה"):
        auto_detect_parser(wb, threshold=0.99)


def test_register_raises_on_duplicate_id():
    register(_FakeParser())
    try:
        with pytest.raises(ValueError, match="already registered"):
            register(_FakeParser())
    finally:
        del PARSER_REGISTRY["fake"]
