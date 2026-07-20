from __future__ import annotations
from datetime import date


def test_derive_is_career_false_before_mandatory_end():
    from app.services.eligibility import derive_is_career
    assert derive_is_career(
        rank="טוראי", mandatory_end_date=date(2027, 1, 1), discharge_date=None,
        today=date(2026, 7, 19),
    ) is False


def test_derive_is_career_true_after_mandatory_end_no_discharge():
    from app.services.eligibility import derive_is_career
    assert derive_is_career(
        rank="רסן", mandatory_end_date=date(2025, 1, 1), discharge_date=None,
        today=date(2026, 7, 19),
    ) is True


def test_derive_is_career_false_when_discharged_before_mandatory_end():
    from app.services.eligibility import derive_is_career
    assert derive_is_career(
        rank="רסן", mandatory_end_date=date(2027, 1, 1), discharge_date=date(2026, 6, 1),
        today=date(2026, 7, 19),
    ) is False
