from __future__ import annotations

from sqlalchemy import select

from app.db.models import AuditLog, SoldierHrProfile
from app.services.hr.divergence import record_sync_divergence


def test_record_sync_divergence_writes_audit_entry(admin_session):
    profile = SoldierHrProfile(personal_number="div-001", raw_dto={}, overridden_fields=["rank"])
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    record_sync_divergence(
        admin_session,
        soldier_hr_profile_id=profile.id,
        field_name="rank",
        hr_value="רב טוראי",
        local_value="סמל",
    )
    admin_session.commit()

    entries = admin_session.execute(
        select(AuditLog).where(AuditLog.entity_id == profile.id)
    ).scalars().all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == "hr_sync.field_skipped_overridden"
    assert entry.entity_type == "soldier_hr_profile"
    assert entry.actor_id is None
    assert entry.context == {"field_name": "rank", "hr_value": "רב טוראי", "local_value": "סמל"}
