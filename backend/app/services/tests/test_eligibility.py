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


def test_derive_is_career_true_when_mandatory_end_equals_discharge_date():
    from app.services.eligibility import derive_is_career
    assert derive_is_career(
        rank="רסן", mandatory_end_date=date(2020, 8, 14), discharge_date=date(2020, 8, 14),
        today=date(2026, 8, 14),
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


def _soldier(rank: str, mandatory_end_date: date | None) -> "Soldier":
    from app.db.models import Soldier
    return Soldier(
        personal_number="1", full_name="Test", password_hash="x",
        rank=rank, is_officer=False, mandatory_end_date=mandatory_end_date, discharge_date=None,
    )


def test_rank_service_types_restricts_only_the_named_rank():
    """A duty open to both סמ"ר and רסל, restricted to career-only for סמ"ר
    specifically, should reject a mandatory-service Samar but still accept a
    mandatory-service רס"ל (unaffected by the override)."""
    from app.services.eligibility import DutyTypeRequirements, _is_eligible

    reqs = DutyTypeRequirements(
        allowed_ranks=["סמר", "רסל"],
        rank_service_types={"סמר": ["קבע"]},
    )
    today = date(2026, 7, 29)

    mandatory_samar = _soldier("סמר", mandatory_end_date=date(2027, 1, 1))  # still חובה
    career_samar = _soldier("סמר", mandatory_end_date=date(2020, 1, 1))  # now קבע
    mandatory_rasal = _soldier("רסל", mandatory_end_date=date(2027, 1, 1))  # still חובה

    assert _is_eligible(mandatory_samar, reqs, mitvahim_months=6, alal_months=3, today=today) is False
    assert _is_eligible(career_samar, reqs, mitvahim_months=6, alal_months=3, today=today) is True
    assert _is_eligible(mandatory_rasal, reqs, mitvahim_months=6, alal_months=3, today=today) is True


def test_rank_service_types_absent_falls_back_to_global_filter():
    """A rank with no entry in rank_service_types keeps using the global
    allowed_service_types filter, unaffected by another rank's override."""
    from app.services.eligibility import DutyTypeRequirements, _is_eligible

    reqs = DutyTypeRequirements(
        allowed_ranks=["סמר", "רסל"],
        allowed_service_types=["חובה"],
        rank_service_types={"סמר": ["קבע"]},
    )
    today = date(2026, 7, 29)

    career_rasal = _soldier("רסל", mandatory_end_date=date(2020, 1, 1))  # now קבע, but רסל not overridden
    mandatory_rasal = _soldier("רסל", mandatory_end_date=date(2027, 1, 1))  # still חובה

    assert _is_eligible(career_rasal, reqs, mitvahim_months=6, alal_months=3, today=today) is False
    assert _is_eligible(mandatory_rasal, reqs, mitvahim_months=6, alal_months=3, today=today) is True


def test_rank_service_types_explicit_empty_list_exempts_rank_from_global_filter():
    """An explicit empty override (rank present in rank_service_types with an
    empty list) means 'no service-type restriction for this rank', overriding
    a global allowed_service_types filter that would otherwise apply."""
    from app.services.eligibility import DutyTypeRequirements, _is_eligible

    reqs = DutyTypeRequirements(
        allowed_ranks=["סמר", "רסל"],
        allowed_service_types=["קבע"],
        rank_service_types={"סמר": []},
    )
    today = date(2026, 7, 29)

    mandatory_samar = _soldier("סמר", mandatory_end_date=date(2027, 1, 1))  # still חובה, exempted rank
    mandatory_rasal = _soldier("רסל", mandatory_end_date=date(2027, 1, 1))  # still חובה, not exempted

    assert _is_eligible(mandatory_samar, reqs, mitvahim_months=6, alal_months=3, today=today) is True
    assert _is_eligible(mandatory_rasal, reqs, mitvahim_months=6, alal_months=3, today=today) is False


def _constraint_base(session):
    """Return (soldier, dt, loc, assignment) with an assignment on 2026-08-10..08-11."""
    from app.db.models import DutyAssignment, DutyLocation, DutyType
    from tests.helpers import create_soldier

    dt = DutyType(name="שמירה-override", score_per_day=1)
    loc = DutyLocation(name="עמדה-override")
    soldier = create_soldier(session, personal_number="override-1")
    session.add_all([dt, loc])
    session.flush()
    # Not "published" — the assignment under evaluation must not count as its
    # own scheduling conflict in step 4 (which only excludes overlapping
    # *other* published assignments when exclude_assignment_id is passed).
    a = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 10), end_date=date(2026, 8, 11), status="algorithm_draft",
    )
    session.add(a)
    session.flush()
    return soldier, dt, loc, a


def _approved_constraint(session, soldier_id, start, end):
    from app.db.models import PersonalConstraint

    c = PersonalConstraint(
        soldier_id=soldier_id, start_date=start, end_date=end,
        reason="r", status="approved",
    )
    session.add(c)
    session.flush()
    return c


def test_constraint_blocks_by_default(admin_session):
    from app.services.eligibility import check_soldier_for_assignment

    soldier, _dt, _loc, a = _constraint_base(admin_session)
    _approved_constraint(admin_session, soldier.id, date(2026, 8, 10), date(2026, 8, 11))

    eligible, reason, warning = check_soldier_for_assignment(admin_session, soldier.id, a.id)
    assert eligible is False
    assert reason == "אילוץ אישי מאושר בתאריך זה"
    assert warning is None


def test_constraint_blocks_even_with_override_flag_if_flag_false(admin_session):
    from app.services.eligibility import check_soldier_for_assignment

    soldier, _dt, _loc, a = _constraint_base(admin_session)
    _approved_constraint(admin_session, soldier.id, date(2026, 8, 10), date(2026, 8, 11))

    eligible, reason, warning = check_soldier_for_assignment(
        admin_session, soldier.id, a.id, allow_constraint_override=False,
    )
    assert eligible is False
    assert warning is None


def test_constraint_becomes_warning_when_override_allowed(admin_session):
    from app.services.eligibility import check_soldier_for_assignment

    soldier, _dt, _loc, a = _constraint_base(admin_session)
    c = _approved_constraint(admin_session, soldier.id, date(2026, 8, 10), date(2026, 8, 11))

    eligible, reason, warning = check_soldier_for_assignment(
        admin_session, soldier.id, a.id, allow_constraint_override=True,
    )
    assert eligible is True
    assert reason is None
    assert warning == {
        "reason": c.reason,
        "start_date": c.start_date,
        "end_date": c.end_date,
        "decided_by": None,
        "decided_at": c.decided_at,
    }


def test_multiple_overlapping_constraints_does_not_raise_and_blocks(admin_session):
    """Nothing in the submit/approval flow prevents a soldier from ending up with
    two overlapping approved PersonalConstraint rows. check_soldier_for_assignment
    must tolerate that data state (not raise sqlalchemy.exc.MultipleResultsFound)
    regardless of allow_constraint_override."""
    from app.services.eligibility import check_soldier_for_assignment

    soldier, _dt, _loc, a = _constraint_base(admin_session)
    _approved_constraint(admin_session, soldier.id, date(2026, 8, 9), date(2026, 8, 12))
    _approved_constraint(admin_session, soldier.id, date(2026, 8, 10), date(2026, 8, 11))

    eligible, reason, warning = check_soldier_for_assignment(admin_session, soldier.id, a.id)
    assert eligible is False
    assert reason == "אילוץ אישי מאושר בתאריך זה"
    assert warning is None


def test_multiple_overlapping_constraints_does_not_raise_with_override_allowed(admin_session):
    from app.services.eligibility import check_soldier_for_assignment

    soldier, _dt, _loc, a = _constraint_base(admin_session)
    _approved_constraint(admin_session, soldier.id, date(2026, 8, 9), date(2026, 8, 12))
    _approved_constraint(admin_session, soldier.id, date(2026, 8, 10), date(2026, 8, 11))

    eligible, reason, warning = check_soldier_for_assignment(
        admin_session, soldier.id, a.id, allow_constraint_override=True,
    )
    assert eligible is True
    assert reason is None
    assert warning is not None
    assert warning["reason"] == "r"
