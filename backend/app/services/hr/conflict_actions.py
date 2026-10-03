"""Admin actions on HR identity conflicts: acknowledge, choose a record, clear a choice.

Each raises :class:`ConflictActionError` with a stable code before changing
anything. ``choose_candidate`` applies the chosen HR record immediately through
the normal sync write path (:func:`app.services.hr.person_sync.apply_hr_record`)
and remembers the choice in :class:`~app.db.models.HrPreferredRecord`. None of
these commit; the route does.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HrIdentityConflict, HrPreferredRecord
from app.services.hr.conflicts import (
    ACTIVE_STATUSES,
    candidate_problem,
    preferred_key,
    record_key,
    soldiers_with_personal_number,
)
from app.services.hr.mapping import HeldForReview, map_hr_user
from app.services.hr.person_sync import apply_hr_record
from app.services.hr.schemas import HrUser


class ConflictActionError(ValueError):
    """Stable error code in ``str(error)``; ``status_code`` is the HTTP mapping."""

    def __init__(self, code: str, status_code: int = 400) -> None:
        self.status_code = status_code
        super().__init__(code)


def _active_conflict(session: Session, conflict_id: uuid.UUID) -> HrIdentityConflict:
    conflict = session.get(HrIdentityConflict, conflict_id)
    if conflict is None:
        raise ConflictActionError("conflict_not_found", 404)
    if conflict.status not in ACTIVE_STATUSES:
        raise ConflictActionError("conflict_not_active", 409)
    return conflict


def candidate_user(candidate: dict) -> HrUser:
    return HrUser.model_validate(candidate["payload"])


def candidate_choice_status(session: Session, conflict: HrIdentityConflict) -> list[str | None]:
    """Per candidate: None if it can be chosen, else the reason code."""
    if conflict.kind != "duplicate_personal_number":
        return ["not_a_duplicate_conflict"] * len(conflict.candidates)
    own = [s.id for s in soldiers_with_personal_number(session, conflict.personal_number)]
    statuses: list[str | None] = []
    for candidate in conflict.candidates:
        user = candidate_user(candidate)
        if isinstance(map_hr_user(user), HeldForReview):
            statuses.append("candidate_held_for_review")
            continue
        problem = candidate_problem(session, user, own_soldier_ids=own)
        if problem is None and _key_count(conflict, candidate) > 1:
            problem = "candidate_key_not_unique"
        statuses.append(problem)
    return statuses


def _key_count(conflict: HrIdentityConflict, candidate: dict) -> int:
    key_type, key_value = candidate.get("key_type"), candidate.get("key_value")
    return sum(
        1 for other in conflict.candidates
        if record_key(candidate_user(other), key_type) == key_value
    )


def acknowledge_conflict(session: Session, conflict_id: uuid.UUID, *, actor_id: uuid.UUID) -> HrIdentityConflict:
    conflict = _active_conflict(session, conflict_id)
    if conflict.status != "open":
        raise ConflictActionError("conflict_not_open", 409)
    conflict.status = "acknowledged"
    conflict.acknowledged_at = datetime.now(tz=timezone.utc)
    conflict.acknowledged_by = actor_id
    write_audit(
        session, actor_id=actor_id, action="hr_sync.identity_conflict.acknowledge",
        entity_type="hr_identity_conflict", entity_id=conflict.id,
        context={"personal_number": conflict.personal_number, "kind": conflict.kind},
    )
    return conflict


def choose_candidate(
    session: Session, conflict_id: uuid.UUID, candidate_index: int, *, actor_id: uuid.UUID,
) -> HrIdentityConflict:
    conflict = _active_conflict(session, conflict_id)
    if conflict.kind != "duplicate_personal_number":
        raise ConflictActionError("not_a_duplicate_conflict")
    if not 0 <= candidate_index < len(conflict.candidates):
        raise ConflictActionError("candidate_not_found")

    problem = candidate_choice_status(session, conflict)[candidate_index]
    if problem is not None:
        raise ConflictActionError(problem)

    candidate = conflict.candidates[candidate_index]
    user = candidate_user(candidate)
    mapped = map_hr_user(user)
    key = preferred_key(user)
    assert key is not None and not isinstance(mapped, HeldForReview)  # guaranteed by the checks above

    apply_hr_record(session, user, mapped, hr_person_sync_id=None)

    now = datetime.now(tz=timezone.utc)
    preference = session.execute(
        select(HrPreferredRecord).where(HrPreferredRecord.personal_number == conflict.personal_number)
    ).scalar_one_or_none()
    if preference is None:
        preference = HrPreferredRecord(
            personal_number=conflict.personal_number, key_type=key[0], key_value=key[1], chosen_by=actor_id,
        )
        session.add(preference)
    else:
        preference.key_type, preference.key_value = key
        preference.chosen_by = actor_id
        preference.chosen_at = now
    conflict.status = "resolved"
    conflict.chosen_index = candidate_index
    conflict.applied_index = candidate_index
    conflict.resolved_at = now
    conflict.resolved_by = actor_id
    session.flush()
    write_audit(
        session, actor_id=actor_id, action="hr_sync.identity_conflict.choose",
        entity_type="hr_identity_conflict", entity_id=conflict.id,
        context={
            "personal_number": conflict.personal_number, "candidate_index": candidate_index,
            "key_type": key[0],
        },
    )
    return conflict


def clear_preference(session: Session, personal_number: str, *, actor_id: uuid.UUID) -> None:
    preference = session.execute(
        select(HrPreferredRecord).where(HrPreferredRecord.personal_number == personal_number)
    ).scalar_one_or_none()
    if preference is None:
        raise ConflictActionError("preference_not_found", 404)
    write_audit(
        session, actor_id=actor_id, action="hr_sync.preferred_record.clear",
        entity_type="hr_preferred_record", entity_id=preference.id,
        context={"personal_number": personal_number, "key_type": preference.key_type},
    )
    session.delete(preference)
