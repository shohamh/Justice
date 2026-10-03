"""Decide "who is this person?" for an SSO claim, and record ambiguity.

:func:`resolve_soldier_identity` is the only code that maps a verified email
plus its derived AD username to a soldier. It returns one of:

* :class:`Match` - exactly one soldier holds *both* values. The soldier may be
  inactive (``left_at`` set); the caller decides whether to reject.
* :class:`NoMatch` - nobody holds either value.
* :class:`Ambiguous` - anything else: more than one soldier, or a soldier that
  matches on only one field (email on one, AD username on another, or a single
  soldier sharing just the AD username from a different mail domain). Ambiguity
  never logs anyone in and never creates a soldier. Callers pass the
  candidates to :func:`record_identity_conflict`.

An admin settles a recorded conflict with :func:`resolve_identity_conflict`
(choose one candidate; later resolutions of the same AD username then return
that soldier as a ``Match``) or :func:`dismiss_identity_conflict` (no choice;
the identity stays ambiguous and a repeat records a new open conflict).

Conflict rows and logs carry soldier ids and the derived AD username only,
never the email address or other claims.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import IdentityConflict, IdentityConflictCandidate, Soldier
from app.services.identity import normalize_email

logger = logging.getLogger(__name__)

CONFLICT_SOURCES = ("sso", "hr_sync", "registration")
MATCHED_FIELDS = ("email", "ad_username")


@dataclass(frozen=True)
class Candidate:
    """A soldier involved in an ambiguity, with the claim fields it matched."""

    soldier_id: uuid.UUID
    matched_fields: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedCandidate:
    soldier: Soldier
    matched_fields: tuple[str, ...]

    def as_candidate(self) -> Candidate:
        return Candidate(self.soldier.id, self.matched_fields)


@dataclass(frozen=True)
class Match:
    soldier: Soldier


@dataclass(frozen=True)
class NoMatch:
    pass


@dataclass(frozen=True)
class Ambiguous:
    candidates: tuple[ResolvedCandidate, ...]

    def as_candidates(self) -> list[Candidate]:
        """Candidates in the form :func:`record_identity_conflict` accepts."""
        return [candidate.as_candidate() for candidate in self.candidates]


IdentityResolution = Match | NoMatch | Ambiguous


def resolve_soldier_identity(
    session: Session, email: str | None, ad_username: str | None
) -> IdentityResolution:
    """Resolve a verified ``email`` and its derived ``ad_username``.

    Both are normalized (trim, lowercase) first and must be non-blank
    (``ValueError("identity_claim_incomplete")`` otherwise). Never raises on
    ambiguity; it returns it.
    """
    normalized_email = normalize_email(email)
    normalized_username = (ad_username or "").strip().lower()
    if normalized_email is None or not normalized_username:
        raise ValueError("identity_claim_incomplete")

    soldiers = session.execute(
        select(Soldier)
        .where(or_(Soldier.email == normalized_email, Soldier.ad_username == normalized_username))
        .execution_options(populate_existing=True)  # never decide on stale in-session values
    ).scalars().all()
    if not soldiers:
        return NoMatch()

    candidates: dict[uuid.UUID, ResolvedCandidate] = {}
    for soldier in soldiers:  # one row per soldier, so already de-duplicated by id
        matched = tuple(
            name
            for name, ok in (
                ("email", soldier.email == normalized_email),
                ("ad_username", soldier.ad_username == normalized_username),
            )
            if ok
        )
        candidates[soldier.id] = ResolvedCandidate(soldier, matched)

    if len(candidates) == 1:
        only = next(iter(candidates.values()))
        if only.matched_fields == MATCHED_FIELDS:
            return Match(only.soldier)

    chosen = _admin_choice(session, normalized_username, candidates)
    if chosen is not None:
        return Match(candidates[chosen].soldier)
    return Ambiguous(tuple(candidates.values()))


def _admin_choice(
    session: Session, ad_username: str, candidates: dict[uuid.UUID, ResolvedCandidate]
) -> uuid.UUID | None:
    """The soldier an admin chose for this AD username, if still a candidate."""
    row = session.execute(
        select(IdentityConflict.chosen_soldier_id)
        .where(
            IdentityConflict.ad_username == ad_username,
            IdentityConflict.status == "resolved",
            IdentityConflict.chosen_soldier_id.is_not(None),
            IdentityConflict.source.in_(("sso", "registration")),
        )
        .order_by(IdentityConflict.resolved_at.desc())
        .limit(1)
    ).first()
    if row is None or row[0] not in candidates:
        return None
    return row[0]


def record_identity_conflict(
    session: Session,
    *,
    source: str,
    ad_username: str,
    candidates: Iterable[Candidate | ResolvedCandidate],
    personal_number: str | None = None,
) -> IdentityConflict:
    """Record (idempotently) that an identity is ambiguous; returns the open row.

    The open row for the same ``(source, ad_username)`` is reused and any new
    candidates are added to it; otherwise a new open conflict is created.
    Emits an ERROR log with soldier ids only when something new was recorded.
    Does not commit.
    """
    if source not in CONFLICT_SOURCES:
        raise ValueError("unknown_conflict_source")
    username = ad_username.strip().lower()
    candidate_list = [
        c.as_candidate() if isinstance(c, ResolvedCandidate) else c for c in candidates
    ]

    conflict = _open_conflict(session, source, username)
    created = False
    if conflict is None:
        conflict = IdentityConflict(
            source=source, ad_username=username, personal_number=personal_number
        )
        try:
            with session.begin_nested():
                session.add(conflict)
                session.flush()
            created = True
        except IntegrityError:
            # A concurrent request recorded the same open conflict first.
            existing = _open_conflict(session, source, username)
            if existing is None:
                raise
            conflict = existing
    if conflict.personal_number is None and personal_number is not None:
        conflict.personal_number = personal_number

    known = {
        row.soldier_id: row
        for row in session.execute(
            select(IdentityConflictCandidate).where(
                IdentityConflictCandidate.conflict_id == conflict.id
            )
        ).scalars()
    }
    added: list[uuid.UUID] = []
    for candidate in candidate_list:
        fields = [name for name in MATCHED_FIELDS if name in candidate.matched_fields]
        row = known.get(candidate.soldier_id)
        if row is None:
            session.add(
                IdentityConflictCandidate(
                    conflict_id=conflict.id, soldier_id=candidate.soldier_id, matched_fields=fields
                )
            )
            added.append(candidate.soldier_id)
        elif set(fields) - set(row.matched_fields):
            row.matched_fields = sorted(set(row.matched_fields) | set(fields))
    session.flush()

    if created or added:
        logger.error(
            "identity conflict %s (source=%s): soldier ids %s",
            "recorded" if created else "extended",
            source,
            ", ".join(str(i) for i in (added or [c.soldier_id for c in candidate_list])),
        )
    return conflict


def _open_conflict(session: Session, source: str, ad_username: str) -> IdentityConflict | None:
    return session.execute(
        select(IdentityConflict).where(
            IdentityConflict.source == source,
            IdentityConflict.ad_username == ad_username,
            IdentityConflict.status == "open",
        )
    ).scalar_one_or_none()


def resolve_identity_conflict(
    session: Session,
    conflict: IdentityConflict,
    *,
    chosen_soldier_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> IdentityConflict:
    """Admin picks the soldier this identity belongs to. Audited; edits nobody else.

    ``ValueError("conflict_not_open")`` if already settled,
    ``ValueError("not_a_candidate")`` if the soldier is not one of the candidates.
    """
    _require_open(conflict)
    candidate_ids = set(
        session.execute(
            select(IdentityConflictCandidate.soldier_id).where(
                IdentityConflictCandidate.conflict_id == conflict.id
            )
        ).scalars()
    )
    if chosen_soldier_id not in candidate_ids:
        raise ValueError("not_a_candidate")
    conflict.status = "resolved"
    conflict.chosen_soldier_id = chosen_soldier_id
    conflict.resolved_by = actor_id
    conflict.resolved_at = datetime.now(timezone.utc)
    write_audit(
        session,
        actor_id=actor_id,
        action="identity_conflict.resolve",
        entity_type="identity_conflict",
        entity_id=conflict.id,
        after={"chosen_soldier_id": str(chosen_soldier_id), "source": conflict.source},
    )
    session.flush()
    return conflict


def dismiss_identity_conflict(
    session: Session,
    conflict: IdentityConflict,
    *,
    reason: str,
    actor_id: uuid.UUID,
) -> IdentityConflict:
    """Admin dismisses the conflict with a mandatory reason. Chooses nobody.

    ``ValueError("conflict_not_open")`` / ``ValueError("reason_required")``.
    """
    _require_open(conflict)
    cleaned = (reason or "").strip()
    if not cleaned:
        raise ValueError("reason_required")
    conflict.status = "dismissed"
    conflict.resolution_note = cleaned
    conflict.resolved_by = actor_id
    conflict.resolved_at = datetime.now(timezone.utc)
    write_audit(
        session,
        actor_id=actor_id,
        action="identity_conflict.dismiss",
        entity_type="identity_conflict",
        entity_id=conflict.id,
        after={"reason": cleaned, "source": conflict.source},
    )
    session.flush()
    return conflict


def _require_open(conflict: IdentityConflict) -> None:
    if conflict.status != "open":
        raise ValueError("conflict_not_open")


def mask_email(email: str | None) -> str | None:
    """``dude@corp.example`` -> ``d***@c***.example`` (for admin display only)."""
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    first_label, _, rest = domain.partition(".")
    tail = f".{rest}" if rest else ""
    return f"{local[:1]}***@{first_label[:1]}***{tail}"
