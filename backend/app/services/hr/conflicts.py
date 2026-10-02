"""HR sync identity conflicts: detection, recording, and admin resolution.

Two kinds of problem are detected without ever failing a sync run:

* the same personal number appears more than once in the HR feed
  (``duplicate_personal_number``). The sync applies the *latest* record (the
  last occurrence; HR records carry no timestamp) unless an admin has chosen a
  different one (:class:`~app.db.models.HrPreferredRecord`);
* an HR email, or the AD username derived from it, cannot be used: it belongs
  to a different soldier (``email_collision`` / ``ad_username_collision``) or
  is unsupported (``email_invalid``). The person's other fields still sync and
  the soldier's email stays unchanged.

Detection raises :class:`~app.services.hr.errors.HrIdentityConflictError`,
which ``run_person_sync`` catches per person and passes to
:func:`record_hr_conflict`. Logs carry personal numbers and soldier ids only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import HrIdentityConflict, HrPreferredRecord, Soldier
from app.services.hr.errors import HrIdentityConflictError
from app.services.hr.schemas import HrUser
from app.services.identity import canonical_identity, normalize_email

logger = logging.getLogger(__name__)

KEY_TYPES = ("t_person_id", "username", "mail")  # priority order
ACTIVE_STATUSES = ("open", "acknowledged")


@dataclass(frozen=True)
class HrCandidate:
    """One HR record involved in a conflict."""

    index: int
    key_type: str | None
    key_value: str | None
    payload: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {
            "index": self.index, "key_type": self.key_type,
            "key_value": self.key_value, "payload": self.payload,
        }


def normalize_personal_number(value: str | None) -> str:
    return (value or "").strip()


def record_key(user: HrUser, key_type: str) -> str | None:
    """The record's value for ``key_type`` (mail normalized), None if absent/unusable."""
    if key_type == "t_person_id":
        value = user.t_person_id
    elif key_type == "username":
        value = user.username
    elif key_type == "mail":
        try:
            return normalize_email(user.mail)
        except ValueError:
            return None
    else:
        raise ValueError(f"unknown key_type {key_type}")
    value = (value or "").strip()
    return value or None


def preferred_key(user: HrUser) -> tuple[str, str] | None:
    """Most stable identifier the record offers: t_person_id, username, then mail."""
    for key_type in KEY_TYPES:
        value = record_key(user, key_type)
        if value is not None:
            return key_type, value
    return None


def build_candidate(index: int, user: HrUser) -> HrCandidate:
    key = preferred_key(user)
    return HrCandidate(
        index=index, key_type=key[0] if key else None, key_value=key[1] if key else None,
        payload=user.model_dump(by_alias=True),
    )


def group_feed_by_personal_number(users: list[HrUser]) -> dict[str, list[int]]:
    """Feed positions per normalized personal number, in feed order."""
    groups: dict[str, list[int]] = {}
    for position, user in enumerate(users):
        personal_number = normalize_personal_number(user.personal_number)
        if personal_number:
            groups.setdefault(personal_number, []).append(position)
    return groups


# ── invariant checks (raise HrIdentityConflictError) ───────────────────────


def soldiers_with_personal_number(session: Session, personal_number: str) -> list[Soldier]:
    """All local soldiers for a personal number (``.all()``, never scalar_one)."""
    return list(session.execute(
        select(Soldier).where(Soldier.personal_number == personal_number)
    ).scalars().all())


def email_problem(
    session: Session, raw_email: str | None, *, own_soldier_ids: list[uuid.UUID] | None = None,
) -> tuple[str, list[str]] | None:
    """Why ``raw_email`` cannot be applied: ``(kind, colliding soldier ids)`` or None."""
    if raw_email is None or not raw_email.strip():
        return None
    try:
        email, ad_username = canonical_identity(raw_email)
    except ValueError:
        return "email_invalid", []
    own = own_soldier_ids or []
    query = select(Soldier.id, Soldier.email, Soldier.ad_username).where(
        or_(Soldier.email == email, Soldier.ad_username == ad_username)
    )
    if own:
        query = query.where(Soldier.id.not_in(own))
    rows = session.execute(query).all()
    if not rows:
        return None
    ids = sorted({str(row.id) for row in rows})
    kind = "email_collision" if any(row.email == email for row in rows) else "ad_username_collision"
    return kind, ids


def ensure_email_applicable(
    session: Session, user: HrUser, *, own_soldier_ids: list[uuid.UUID] | None = None,
) -> None:
    """Raise :class:`HrIdentityConflictError` if the record's email cannot be applied."""
    problem = email_problem(session, user.mail, own_soldier_ids=own_soldier_ids)
    if problem is None:
        return
    kind, ids = problem
    raise HrIdentityConflictError(
        personal_number=normalize_personal_number(user.personal_number), kind=kind,
        reason="email_not_applied", candidates=[build_candidate(0, user)],
        applied_index=0, colliding_soldier_ids=ids,
    )


def candidate_problem(session: Session, user: HrUser, *, own_soldier_ids: list[uuid.UUID]) -> str | None:
    """Why a duplicate-record candidate cannot be chosen as the preferred record.

    A choosable candidate has a key, a valid email with a derived AD username,
    and no collision with a different soldier. Returns a stable code or None.
    """
    if preferred_key(user) is None:
        return "candidate_has_no_key"
    if user.mail is None or not user.mail.strip():
        return "email_missing"
    problem = email_problem(session, user.mail, own_soldier_ids=own_soldier_ids)
    if problem is None:
        return None
    kind, _ids = problem
    if kind == "email_invalid":
        try:
            canonical_identity(user.mail)
        except ValueError as exc:
            return str(exc)
        return "email_invalid"
    return "email_taken" if kind == "email_collision" else "ad_username_taken"


# ── duplicate decisions ────────────────────────────────────────────────────


@dataclass(frozen=True)
class DuplicatePlan:
    """Decision for a personal number that appears more than once in the feed."""

    personal_number: str
    positions: list[int]
    applied_position: int
    error: HrIdentityConflictError | None  # None: applied the remembered choice, no warning


def latest_plan(
    personal_number: str, positions: list[int], users: list[HrUser], *, reason: str,
) -> DuplicatePlan:
    """The default decision: apply the latest record and warn."""
    candidates = [build_candidate(i, users[p]) for i, p in enumerate(positions)]
    error = HrIdentityConflictError(
        personal_number=personal_number, kind="duplicate_personal_number", reason=reason,
        candidates=candidates, applied_index=len(positions) - 1,
    )
    return DuplicatePlan(personal_number, positions, positions[-1], error)


def plan_duplicate(
    session: Session, personal_number: str, positions: list[int], users: list[HrUser],
) -> DuplicatePlan:
    preference = session.execute(
        select(HrPreferredRecord).where(HrPreferredRecord.personal_number == personal_number)
    ).scalar_one_or_none()
    if preference is None:
        return latest_plan(personal_number, positions, users, reason="latest")

    matches = [
        i for i, p in enumerate(positions)
        if record_key(users[p], preference.key_type) == preference.key_value
    ]
    if not matches:
        return latest_plan(personal_number, positions, users, reason="preferred_stale")
    if len(matches) > 1:
        return latest_plan(personal_number, positions, users, reason="preferred_ambiguous")
    own = [s.id for s in soldiers_with_personal_number(session, personal_number)]
    if candidate_problem(session, users[positions[matches[0]]], own_soldier_ids=own) is not None:
        return latest_plan(personal_number, positions, users, reason="preferred_invalid")
    return DuplicatePlan(personal_number, positions, positions[matches[0]], None)


def ensure_no_unresolved_duplicate(plan: DuplicatePlan | None) -> None:
    """Raise the plan's conflict error when the duplicate was not settled by a preference."""
    if plan is not None and plan.error is not None:
        raise plan.error


# ── recording ──────────────────────────────────────────────────────────────


def _fingerprint(error: HrIdentityConflictError) -> str:
    material = {
        "kind": error.kind, "reason": error.reason, "applied": error.applied_index,
        "colliding": sorted(error.colliding_soldier_ids),
        "candidates": [c.as_json() for c in error.candidates],
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()


def record_hr_conflict(
    session: Session, error: HrIdentityConflictError, *, hr_person_sync_id: uuid.UUID | None,
) -> bool:
    """Persist ``error`` as a warning. Returns True if it should count for this run.

    Idempotent per (personal number, kind) while active: an unchanged open row is
    refreshed (and counted again, since the conflict is still there); an
    unchanged acknowledged row stays quiet (not counted); a changed row is
    updated and reopened. Does not commit.
    """
    fingerprint = _fingerprint(error)
    now = datetime.now(tz=timezone.utc)
    row = session.execute(
        select(HrIdentityConflict).where(
            HrIdentityConflict.personal_number == error.personal_number,
            HrIdentityConflict.kind == error.kind,
            HrIdentityConflict.status.in_(ACTIVE_STATUSES),
        )
    ).scalar_one_or_none()

    if row is not None and row.fingerprint == fingerprint:
        row.last_seen_at = now
        if row.status == "acknowledged":
            return False
        row.hr_person_sync_id = hr_person_sync_id
    else:
        if row is None:
            row = HrIdentityConflict(
                personal_number=error.personal_number, kind=error.kind, reason=error.reason,
                candidates=[], fingerprint=fingerprint,
            )
            session.add(row)
        row.reason = error.reason
        row.candidates = [c.as_json() for c in error.candidates]
        row.fingerprint = fingerprint
        row.applied_index = error.applied_index
        row.colliding_soldier_ids = list(error.colliding_soldier_ids)
        row.status = "open"
        row.acknowledged_at = None
        row.acknowledged_by = None
        row.hr_person_sync_id = hr_person_sync_id
        row.last_seen_at = now
    session.flush()
    logger.warning(
        "HR sync identity conflict: personal_number=%s kind=%s reason=%s candidates=%d applied_index=%s "
        "colliding_soldier_ids=%s",
        error.personal_number, error.kind, error.reason, len(error.candidates),
        error.applied_index, error.colliding_soldier_ids,
    )
    return True
