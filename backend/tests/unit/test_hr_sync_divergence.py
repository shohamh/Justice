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


def test_record_sync_divergence_serializes_date_values(admin_session):
    """Final-review Finding 2: `hr_value`/`local_value` can be `date`
    objects (e.g. mandatory_end_date, discharge_date) which aren't
    JSON-native — they must be converted to ISO strings before landing in
    the JSONB `context` column, or a real sync run would raise TypeError."""
    from datetime import date

    profile = SoldierHrProfile(
        personal_number="div-002", raw_dto={}, overridden_fields=["mandatory_end_date"]
    )
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    record_sync_divergence(
        admin_session,
        soldier_hr_profile_id=profile.id,
        field_name="mandatory_end_date",
        hr_value=date(2026, 1, 1),
        local_value="2027-06-15",
    )
    admin_session.commit()

    entry = admin_session.execute(
        select(AuditLog).where(AuditLog.entity_id == profile.id)
    ).scalars().one()
    assert entry.context["hr_value"] == "2026-01-01"
    assert isinstance(entry.context["hr_value"], str)
    assert entry.context["local_value"] == "2027-06-15"
