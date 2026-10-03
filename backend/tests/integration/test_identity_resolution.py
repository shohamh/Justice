"""resolve_soldier_identity and record_identity_conflict."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import select, text

from app.db.models import IdentityConflict, IdentityConflictCandidate, Soldier
from app.services.identity_resolution import (
    Ambiguous,
    Candidate,
    Match,
    NoMatch,
    dismiss_identity_conflict,
    record_identity_conflict,
    resolve_identity_conflict,
    resolve_soldier_identity,
)
from tests.helpers import create_soldier, set_soldier_email


def _soldier(session, pn, email=None, left_at=None):
    s = create_soldier(session, personal_number=pn)
    if email is not None:
        set_soldier_email(s, email)
    s.left_at = left_at
    session.commit()
    return s


@contextmanager
def _legacy_data(session):
    """Relax the identity constraints inside one rolled-back transaction so a test
    can model rows written before they existed. DDL is transactional in
    PostgreSQL; the rollback restores the shared worker schema."""
    session.commit()
    session.execute(text("DROP INDEX uq_soldiers_email"))
    session.execute(text("DROP INDEX uq_soldiers_ad_username"))
    session.execute(text("ALTER TABLE soldiers DROP CONSTRAINT ck_soldiers_email_ad_username_pair"))
    try:
        yield
    finally:
        session.rollback()


def _force_identity(session, soldier, email, ad_username):
    session.execute(
        text("UPDATE soldiers SET email = :e, ad_username = :a WHERE id = :i"),
        {"e": email, "a": ad_username, "i": soldier.id},
    )


def test_match_when_exactly_one_soldier_matches_both_fields(admin_session):
    s = _soldier(admin_session, "ir-1", "Dude@Gmail.com")
    _soldier(admin_session, "ir-2", "other@gmail.com")
    result = resolve_soldier_identity(admin_session, " DUDE@gmail.com ", "Dude")
    assert isinstance(result, Match)
    assert result.soldier.id == s.id


def test_no_match_when_nobody_has_either_field(admin_session):
    _soldier(admin_session, "ir-1", "other@gmail.com")
    assert resolve_soldier_identity(admin_session, "dude@gmail.com", "dude") == NoMatch()


def test_match_returns_inactive_soldier_for_the_caller_to_reject(admin_session):
    s = _soldier(admin_session, "ir-1", "dude@gmail.com", left_at=date(2020, 1, 1))
    result = resolve_soldier_identity(admin_session, "dude@gmail.com", "dude")
    assert isinstance(result, Match)
    assert result.soldier.id == s.id
    assert result.soldier.left_at is not None


def test_ambiguous_when_only_ad_username_matches_other_domain(admin_session):
    s = _soldier(admin_session, "ir-1", "dude@corp.example")
    result = resolve_soldier_identity(admin_session, "dude@gmail.com", "dude")
    assert isinstance(result, Ambiguous)
    assert [(c.soldier.id, c.matched_fields) for c in result.candidates] == [
        (s.id, ("ad_username",))
    ]


def test_ambiguous_when_email_matches_a_and_ad_username_matches_b(admin_session):
    a = _soldier(admin_session, "ir-1", "dude@gmail.com")
    b = _soldier(admin_session, "ir-2", "someone@x.example")
    with _legacy_data(admin_session):
        # Legacy row: B owns the AD username "dude" while A owns the email.
        _force_identity(admin_session, b, "someone@x.example", "dude")
        _force_identity(admin_session, a, "dude@gmail.com", "other")
        result = resolve_soldier_identity(admin_session, "dude@gmail.com", "dude")
    assert isinstance(result, Ambiguous)
    by_id = {c.soldier.id: c.matched_fields for c in result.candidates}
    assert by_id == {a.id: ("email",), b.id: ("ad_username",)}


def test_ambiguous_when_two_soldiers_match_the_same_claim_in_legacy_data(admin_session):
    a = _soldier(admin_session, "ir-1", "dude@gmail.com")
    b = _soldier(admin_session, "ir-2", "x@x.example")
    with _legacy_data(admin_session):
        _force_identity(admin_session, b, "dude@gmail.com", "dude")
        result = resolve_soldier_identity(admin_session, "dude@gmail.com", "dude")
    assert isinstance(result, Ambiguous)
    assert {c.soldier.id for c in result.candidates} == {a.id, b.id}
    assert all(c.matched_fields == ("email", "ad_username") for c in result.candidates)


def test_resolve_requires_a_complete_claim(admin_session):
    with pytest.raises(ValueError):
        resolve_soldier_identity(admin_session, "", "dude")
    with pytest.raises(ValueError):
        resolve_soldier_identity(admin_session, "dude@gmail.com", " ")


def test_resolve_never_raises_on_ambiguity(admin_session):
    _soldier(admin_session, "ir-1", "dude@corp.example")
    assert isinstance(resolve_soldier_identity(admin_session, "dude@gmail.com", "dude"), Ambiguous)


# ── conflict recording ──────────────────────────────────────────────────────


def _ambiguous(session):
    a = _soldier(session, "ir-1", "dude@corp.example")
    result = resolve_soldier_identity(session, "dude@gmail.com", "dude")
    assert isinstance(result, Ambiguous)
    return a, result


def test_record_conflict_stores_candidates_and_is_idempotent(admin_session):
    a, result = _ambiguous(admin_session)
    first = record_identity_conflict(admin_session, source="sso", ad_username="dude",
                                     candidates=result.candidates)
    again = record_identity_conflict(admin_session, source="sso", ad_username="dude",
                                     candidates=result.candidates)
    admin_session.commit()
    assert first.id == again.id
    assert first.status == "open"
    rows = admin_session.execute(select(IdentityConflict)).scalars().all()
    assert len(rows) == 1
    cands = admin_session.execute(select(IdentityConflictCandidate)).scalars().all()
    assert [(c.soldier_id, c.matched_fields) for c in cands] == [(a.id, ["ad_username"])]


def test_record_conflict_separates_sources_and_adds_new_candidates(admin_session):
    a, result = _ambiguous(admin_session)
    sso = record_identity_conflict(admin_session, source="sso", ad_username="dude",
                                   candidates=result.candidates)
    reg = record_identity_conflict(admin_session, source="registration", ad_username="dude",
                                   candidates=result.candidates, personal_number="1234567")
    b = _soldier(admin_session, "ir-2", "b@b.example")
    sso_again = record_identity_conflict(
        admin_session, source="sso", ad_username="dude",
        candidates=[*result.candidates, Candidate(soldier_id=b.id, matched_fields=("email",))],
    )
    admin_session.commit()
    assert sso.id != reg.id
    assert reg.personal_number == "1234567"
    assert sso_again.id == sso.id
    ids = {c.soldier_id for c in admin_session.execute(
        select(IdentityConflictCandidate).where(IdentityConflictCandidate.conflict_id == sso.id)
    ).scalars()}
    assert ids == {a.id, b.id}


def test_record_conflict_rejects_unknown_source(admin_session):
    with pytest.raises(ValueError):
        record_identity_conflict(admin_session, source="nope", ad_username="dude", candidates=[])


def test_record_conflict_logs_ids_only_without_email_or_claims(admin_session, caplog):
    a, result = _ambiguous(admin_session)
    with caplog.at_level(logging.ERROR):
        record_identity_conflict(admin_session, source="sso", ad_username="dude",
                                 candidates=result.candidates)
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    text_ = caplog.text.lower()
    assert str(a.id) in text_
    assert "gmail" not in text_ and "corp.example" not in text_ and "dude" not in text_


# ── resolution transitions ──────────────────────────────────────────────────


def test_resolve_marks_conflict_audits_and_next_resolution_returns_chosen_match(admin_session):
    a, result = _ambiguous(admin_session)
    admin = create_soldier(admin_session, personal_number="ir-adm", role="admin")
    conflict = record_identity_conflict(admin_session, source="sso", ad_username="dude",
                                        candidates=result.candidates)
    admin_session.commit()
    resolve_identity_conflict(admin_session, conflict, chosen_soldier_id=a.id, actor_id=admin.id)
    admin_session.commit()
    admin_session.refresh(conflict)
    assert (conflict.status, conflict.resolved_by, conflict.chosen_soldier_id) == ("resolved", admin.id, a.id)
    assert conflict.resolved_at is not None
    # the next SSO attempt links to the admin's choice
    nxt = resolve_soldier_identity(admin_session, "dude@gmail.com", "dude")
    assert isinstance(nxt, Match) and nxt.soldier.id == a.id
    # other candidates are not edited
    assert admin_session.get(Soldier, a.id).email == "dude@corp.example"


def test_resolve_requires_open_conflict_and_a_candidate(admin_session):
    a, result = _ambiguous(admin_session)
    stranger = _soldier(admin_session, "ir-9", "z@z.example")
    admin = create_soldier(admin_session, personal_number="ir-adm", role="admin")
    conflict = record_identity_conflict(admin_session, source="sso", ad_username="dude",
                                        candidates=result.candidates)
    admin_session.commit()
    with pytest.raises(ValueError, match="not_a_candidate"):
        resolve_identity_conflict(admin_session, conflict, chosen_soldier_id=stranger.id, actor_id=admin.id)
    resolve_identity_conflict(admin_session, conflict, chosen_soldier_id=a.id, actor_id=admin.id)
    with pytest.raises(ValueError, match="conflict_not_open"):
        resolve_identity_conflict(admin_session, conflict, chosen_soldier_id=a.id, actor_id=admin.id)


def test_dismiss_requires_reason_and_leaves_ambiguity_detectable(admin_session):
    _a, result = _ambiguous(admin_session)
    admin = create_soldier(admin_session, personal_number="ir-adm", role="admin")
    conflict = record_identity_conflict(admin_session, source="sso", ad_username="dude",
                                        candidates=result.candidates)
    admin_session.commit()
    with pytest.raises(ValueError, match="reason_required"):
        dismiss_identity_conflict(admin_session, conflict, reason="  ", actor_id=admin.id)
    dismiss_identity_conflict(admin_session, conflict, reason="duplicate report", actor_id=admin.id)
    admin_session.commit()
    admin_session.refresh(conflict)
    assert (conflict.status, conflict.resolution_note) == ("dismissed", "duplicate report")
    # dismissing does not choose anyone: the identity stays ambiguous and a new open conflict is recorded
    assert isinstance(resolve_soldier_identity(admin_session, "dude@gmail.com", "dude"), Ambiguous)
    again = record_identity_conflict(admin_session, source="sso", ad_username="dude",
                                     candidates=result.candidates)
    assert again.id != conflict.id and again.status == "open"
