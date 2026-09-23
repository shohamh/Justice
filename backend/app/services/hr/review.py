from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import SoldierHrProfile
from app.services.hr.mapping import HR_OWNED_FIELDS


class ReviewActionError(Exception):
    pass


def dismiss_held_for_review(
    session: Session, *, profile_id: uuid.UUID, actor_id: uuid.UUID | None = None,
) -> SoldierHrProfile:
    profile = session.get(SoldierHrProfile, profile_id)
    if profile is None:
        raise ReviewActionError("profile_not_found")
    if profile.sync_status != "held_for_review":
        raise ReviewActionError("not_held_for_review")

    reasons = profile.review_reason.split("; ") if profile.review_reason else []
    profile.review_dismissed_at = datetime.now(tz=UTC)
    profile.review_dismissed_reasons = reasons
    write_audit(
        session, actor_id=actor_id, action="hr_sync.review_dismissed",
        entity_type="soldier_hr_profile", entity_id=profile.id,
        context={"reasons": reasons},
    )
    return profile


def clear_field_override(
    session: Session, *, profile_id: uuid.UUID, field_name: str, actor_id: uuid.UUID | None = None,
) -> SoldierHrProfile:
    profile = session.get(SoldierHrProfile, profile_id)
    if profile is None:
        raise ReviewActionError("profile_not_found")
    if field_name not in HR_OWNED_FIELDS:
        raise ReviewActionError("unknown_field")
    if field_name not in profile.overridden_fields:
        raise ReviewActionError("field_not_overridden")

    before = list(profile.overridden_fields)
    profile.overridden_fields = [f for f in profile.overridden_fields if f != field_name]
    write_audit(
        session, actor_id=actor_id, action="hr_sync.override_cleared",
        entity_type="soldier_hr_profile", entity_id=profile.id,
        context={"field_name": field_name, "before": before, "after": profile.overridden_fields},
    )
    return profile
