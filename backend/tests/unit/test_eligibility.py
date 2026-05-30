from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import Soldier
from app.services.eligibility import (
    DutyTypeRequirements,
    _is_eligible,
    inferred_service_type,
)


def _soldier(**kwargs) -> Soldier:
    defaults = dict(
        personal_number="test",
        full_name="Test",
        password_hash="x",
        role="soldier",
        enrolled_at=date(2024, 1, 1),
        bahad1_graduate=False,
    )
    defaults.update(kwargs)
    return Soldier(**defaults)


TODAY = date(2026, 6, 1)


def test_service_type_hobah():
    s = _soldier(mandatory_end_date=date(2027, 1, 1))
    assert inferred_service_type(s, TODAY) == "חובה"


def test_service_type_keva():
    s = _soldier(mandatory_end_date=date(2025, 1, 1), discharge_date=None)
    assert inferred_service_type(s, TODAY) == "קבע"


def test_service_type_unknown():
    s = _soldier()
    assert inferred_service_type(s, TODAY) is None


def test_no_requirements_passes():
    s = _soldier()
    reqs = DutyTypeRequirements()
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_gender_restriction_passes():
    s = _soldier(gender="male")
    reqs = DutyTypeRequirements(allowed_genders=["male"])
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_gender_restriction_blocks():
    s = _soldier(gender="female")
    reqs = DutyTypeRequirements(allowed_genders=["male"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_null_gender_blocked_if_restriction():
    s = _soldier(gender=None)
    reqs = DutyTypeRequirements(allowed_genders=["male"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_mitvahim_fresh_passes():
    s = _soldier(last_mitvahim_date=TODAY - timedelta(days=30))
    reqs = DutyTypeRequirements(requires_mitvahim=True)
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_mitvahim_stale_blocks():
    s = _soldier(last_mitvahim_date=TODAY - timedelta(days=200))
    reqs = DutyTypeRequirements(requires_mitvahim=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_null_mitvahim_blocks():
    s = _soldier(last_mitvahim_date=None)
    reqs = DutyTypeRequirements(requires_mitvahim=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_rank_restriction_passes():
    s = _soldier(rank="סמל")
    reqs = DutyTypeRequirements(allowed_ranks=["סמל", "סמר"])
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_rank_restriction_blocks():
    s = _soldier(rank="טוראי")
    reqs = DutyTypeRequirements(allowed_ranks=["סמל", "סמר"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_null_rank_blocked_if_restriction():
    s = _soldier(rank=None)
    reqs = DutyTypeRequirements(allowed_ranks=["סמל"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_officers_not_allowed():
    s = _soldier(is_officer=True)
    reqs = DutyTypeRequirements(officers_allowed=False)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_enlisted_not_allowed():
    s = _soldier(is_officer=False)
    reqs = DutyTypeRequirements(enlisted_allowed=False)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_bahad1_required_passes():
    s = _soldier(bahad1_graduate=True)
    reqs = DutyTypeRequirements(requires_bahad1=True)
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_bahad1_required_blocks():
    s = _soldier(bahad1_graduate=False)
    reqs = DutyTypeRequirements(requires_bahad1=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_service_type_restriction_blocks():
    s = _soldier(mandatory_end_date=date(2025, 1, 1), discharge_date=None)
    # soldier is קבע, but restriction only allows חובה
    reqs = DutyTypeRequirements(allowed_service_types=["חובה"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)
