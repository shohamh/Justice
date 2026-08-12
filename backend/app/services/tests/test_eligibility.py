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


def test_kaam_is_officer_rank_below_rasan():
    from app.services.eligibility import OFFICER_RANKS
    assert "קאם" in OFFICER_RANKS
    assert OFFICER_RANKS.index("קאם") < OFFICER_RANKS.index("רסן")


def test_kaam_is_keva_only():
    from app.services.eligibility import validate_rank_track_compatibility
    import pytest
    with pytest.raises(ValueError, match="rank_track_incompatible"):
        validate_rank_track_compatibility(rank="קאם", is_career=False)
    validate_rank_track_compatibility(rank="קאם", is_career=True)  # should not raise


def test_sgan_is_ambiguous_and_accepts_either_track():
    from app.services.eligibility import validate_rank_track_compatibility
    validate_rank_track_compatibility(rank="סגן", is_career=True)
    validate_rank_track_compatibility(rank="סגן", is_career=False)


def test_samal_rishon_is_unrestricted_and_accepts_either_track():
    from app.services.eligibility import validate_rank_track_compatibility
    validate_rank_track_compatibility(rank="סמר", is_career=True)
    validate_rank_track_compatibility(rank="סמר", is_career=False)  # should not raise


def test_unknown_rank_is_not_restricted():
    from app.services.eligibility import validate_rank_track_compatibility
    validate_rank_track_compatibility(rank="not_a_real_rank", is_career=True)


def test_derive_bahad1_graduate_true_for_regular_officer():
    from app.services.eligibility import derive_bahad1_graduate
    assert derive_bahad1_graduate("סרן") is True
    assert derive_bahad1_graduate("רסן") is True
    assert derive_bahad1_graduate("סגן") is True


def test_derive_bahad1_graduate_false_for_excluded_officer_ranks():
    from app.services.eligibility import derive_bahad1_graduate
    assert derive_bahad1_graduate("קמא") is False
    assert derive_bahad1_graduate("קאב") is False
    assert derive_bahad1_graduate("קאם") is False


def test_derive_bahad1_graduate_false_for_enlisted_and_unknown():
    from app.services.eligibility import derive_bahad1_graduate
    assert derive_bahad1_graduate("טוראי") is False
    assert derive_bahad1_graduate(None) is False
    assert derive_bahad1_graduate("not_a_real_rank") is False


def test_enlisted_keva_soldier_is_eligible_for_at_least_one_seeded_duty_type(db_admin_url: str):
    """Regression for the seed-data bug where every enlisted duty type's
    requirements set allowed_service_types: ["חובה"] only, making enlisted
    קבע soldiers (e.g. career-track רס"ל) ineligible for every duty type.

    Runs the real seed script against a live test DB and checks the actual
    seeded DutyType rows, so this fails before the seed.py fix and passes
    after it — it is not testing a hand-written duty-type shape.
    """
    from app.db.models import DutyType, Soldier
    from app.db.session import SessionLocal
    from app.scripts import seed as seed_module
    from app.services.eligibility import DutyTypeRequirements, _is_eligible

    seed_module.seed(force=True)

    with SessionLocal() as s:
        duty_types = s.query(DutyType).all()

        keva_enlisted_soldier = Soldier(
            personal_number="99999999",
            full_name="Test Keva NCO",
            password_hash="x",
            rank="רסל",
            is_officer=False,
            is_career=True,
            mandatory_end_date=date(2020, 1, 1),  # long past -> inferred_service_type == "קבע"
            discharge_date=None,
        )

        eligible = []
        for dt in duty_types:
            raw = dt.requirements or {}
            reqs = DutyTypeRequirements.model_validate(raw)
            if _is_eligible(
                keva_enlisted_soldier, reqs,
                mitvahim_months=6, alal_months=3, today=date(2026, 7, 29),
            ):
                eligible.append(dt.name)

        assert len(eligible) > 0, "an enlisted קבע soldier should qualify for at least one seeded duty type"
