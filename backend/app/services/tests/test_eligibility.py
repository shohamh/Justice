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


def test_chovah_only_rank_rejects_career_track():
    from app.services.eligibility import validate_rank_track_compatibility
    import pytest
    with pytest.raises(ValueError, match="rank_track_incompatible"):
        validate_rank_track_compatibility(rank="טוראי", is_career=True)


def test_chovah_only_rank_accepts_mandatory_track():
    from app.services.eligibility import validate_rank_track_compatibility
    validate_rank_track_compatibility(rank="טוראי", is_career=False)  # should not raise


def test_keva_only_rank_rejects_mandatory_track():
    from app.services.eligibility import validate_rank_track_compatibility
    import pytest
    with pytest.raises(ValueError, match="rank_track_incompatible"):
        validate_rank_track_compatibility(rank="רסל", is_career=False)


def test_keva_only_rank_accepts_career_track():
    from app.services.eligibility import validate_rank_track_compatibility
    validate_rank_track_compatibility(rank="רסל", is_career=True)  # should not raise


def test_kaab_is_keva_only():
    from app.services.eligibility import validate_rank_track_compatibility
    import pytest
    with pytest.raises(ValueError, match="rank_track_incompatible"):
        validate_rank_track_compatibility(rank="קאב", is_career=False)
    validate_rank_track_compatibility(rank="קאב", is_career=True)  # should not raise


def test_saren_is_keva_only():
    from app.services.eligibility import validate_rank_track_compatibility
    import pytest
    with pytest.raises(ValueError, match="rank_track_incompatible"):
        validate_rank_track_compatibility(rank="סרן", is_career=False)
    validate_rank_track_compatibility(rank="סרן", is_career=True)  # should not raise


def test_sgan_is_ambiguous_and_accepts_either_track():
    from app.services.eligibility import validate_rank_track_compatibility
    validate_rank_track_compatibility(rank="סגן", is_career=True)
    validate_rank_track_compatibility(rank="סגן", is_career=False)


def test_unknown_rank_is_not_restricted():
    from app.services.eligibility import validate_rank_track_compatibility
    validate_rank_track_compatibility(rank="not_a_real_rank", is_career=True)
