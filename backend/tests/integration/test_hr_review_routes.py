from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db.models import HrRankConflict, SoldierHrProfile
from tests.helpers import auth_headers, create_soldier


def _admin_headers(session):
    admin = create_soldier(session, personal_number="hrr-admin", role="admin")
    return auth_headers(admin)


def test_non_admin_gets_403(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="hrr-1")
    r = client.get("/api/admin/hr-sync/held-for-review", headers=auth_headers(soldier))
    assert r.status_code == 403


def test_held_for_review_excludes_dismissed_unchanged_records(client, admin_session):
    headers = _admin_headers(admin_session)
    admin_session.add_all([
        SoldierHrProfile(
            personal_number="hrr-2", raw_dto={}, sync_status="held_for_review",
            review_reason="bad date",
        ),
        SoldierHrProfile(
            personal_number="hrr-3", raw_dto={}, sync_status="held_for_review",
            review_reason="bad date",
            review_dismissed_at=datetime.now(tz=UTC),
            review_dismissed_reasons=["bad date"],
        ),
    ])
    admin_session.commit()

    r = client.get("/api/admin/hr-sync/held-for-review", headers=headers)
    assert r.status_code == 200
    personal_numbers = {item["personal_number"] for item in r.json()["items"]}
    assert "hrr-2" in personal_numbers
    assert "hrr-3" not in personal_numbers


def test_dismiss_held_for_review_action(client, admin_session):
    headers = _admin_headers(admin_session)
    profile = SoldierHrProfile(
        personal_number="hrr-4", raw_dto={}, sync_status="held_for_review", review_reason="bad date",
    )
    admin_session.add(profile)
    admin_session.commit()

    r = client.post(f"/api/admin/hr-sync/held-for-review/{profile.id}/dismiss", headers=headers)
    assert r.status_code == 200
    admin_session.refresh(profile)
    assert profile.review_dismissed_at is not None


def test_dismiss_held_for_review_returns_404_for_unknown_profile(client, admin_session):
    headers = _admin_headers(admin_session)
    r = client.post(
        f"/api/admin/hr-sync/held-for-review/{uuid.uuid4()}/dismiss", headers=headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "profile_not_found"


def test_dismiss_held_for_review_returns_409_when_not_held(client, admin_session):
    headers = _admin_headers(admin_session)
    profile = SoldierHrProfile(personal_number="hrr-4b", raw_dto={}, sync_status="synced")
    admin_session.add(profile)
    admin_session.commit()

    r = client.post(f"/api/admin/hr-sync/held-for-review/{profile.id}/dismiss", headers=headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "not_held_for_review"


def test_divergences_lists_field_skipped_overridden_audit_rows(client, admin_session):
    headers = _admin_headers(admin_session)
    soldier = create_soldier(admin_session, personal_number="hrr-5")
    profile = SoldierHrProfile(
        personal_number="hrr-5", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["phone"],
    )
    admin_session.add(profile)
    admin_session.commit()

    from app.services.hr.divergence import record_sync_divergence
    record_sync_divergence(
        admin_session, soldier_hr_profile_id=profile.id, field_name="phone",
        hr_value="050-1112222", local_value="050-9998888",
    )
    admin_session.commit()

    r = client.get("/api/admin/hr-sync/divergences", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["field_name"] == "phone"


def test_clear_override_action(client, admin_session):
    headers = _admin_headers(admin_session)
    soldier = create_soldier(admin_session, personal_number="hrr-6")
    profile = SoldierHrProfile(
        personal_number="hrr-6", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["phone"],
    )
    admin_session.add(profile)
    admin_session.commit()

    r = client.post(
        f"/api/admin/hr-sync/divergences/{profile.id}/clear-override",
        headers=headers, json={"field_name": "phone"},
    )
    assert r.status_code == 200
    admin_session.refresh(profile)
    assert profile.overridden_fields == []


def test_clear_override_returns_404_for_unknown_profile(client, admin_session):
    headers = _admin_headers(admin_session)
    r = client.post(
        f"/api/admin/hr-sync/divergences/{uuid.uuid4()}/clear-override",
        headers=headers, json={"field_name": "phone"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "profile_not_found"


def test_clear_override_returns_400_for_unknown_field_name(client, admin_session):
    headers = _admin_headers(admin_session)
    soldier = create_soldier(admin_session, personal_number="hrr-6b")
    profile = SoldierHrProfile(
        personal_number="hrr-6b", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["phone"],
    )
    admin_session.add(profile)
    admin_session.commit()

    r = client.post(
        f"/api/admin/hr-sync/divergences/{profile.id}/clear-override",
        headers=headers, json={"field_name": "not_a_real_field"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "unknown_field"


def test_vanished_lists_vanished_profiles(client, admin_session):
    headers = _admin_headers(admin_session)
    admin_session.add(SoldierHrProfile(personal_number="hrr-7", raw_dto={}, sync_status="vanished"))
    admin_session.commit()

    r = client.get("/api/admin/hr-sync/vanished", headers=headers)
    assert r.status_code == 200
    assert any(item["personal_number"] == "hrr-7" for item in r.json()["items"])


def test_rank_conflicts_lists_conflicts(client, admin_session):
    headers = _admin_headers(admin_session)
    soldier = create_soldier(admin_session, personal_number="hrr-8")
    admin_session.add(HrRankConflict(
        soldier_id=soldier.id, old_rank="טוראי", new_rank="סמל",
        triggered_by_worker_decision=True, non_sequential_jump=False,
    ))
    admin_session.commit()

    r = client.get("/api/admin/hr-sync/rank-conflicts", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["old_rank"] == "טוראי"


def test_sync_runs_lists_recent_runs(client, admin_session):
    headers = _admin_headers(admin_session)
    from app.db.models import HrPersonSync
    run = HrPersonSync(status="completed", total_fetched=10, created_count=2, updated_count=8)
    admin_session.add(run)
    admin_session.commit()

    r = client.get("/api/admin/hr-sync/runs", headers=headers)
    assert r.status_code == 200
    assert any(item["id"] == str(run.id) for item in r.json()["person_syncs"])


def test_run_now_requires_hr_sync_configured(client, admin_session, monkeypatch):
    headers = _admin_headers(admin_session)

    from app.settings import get_settings
    get_settings.cache_clear()
    monkeypatch.delenv("HR_API_BASE_URL", raising=False)
    monkeypatch.delenv("HR_API_KEY", raising=False)

    r = client.post("/api/admin/hr-sync/run-now", headers=headers)
    assert r.status_code == 409
    get_settings.cache_clear()


def test_run_now_triggers_sync(client, admin_session, monkeypatch):
    headers = _admin_headers(admin_session)
    from unittest.mock import AsyncMock

    import app.routes.hr_review as hr_review_module
    from app.db.models import HrHierarchySync, HrPersonSync

    async def _fake_hierarchy_sync(session, client_):
        run = HrHierarchySync(status="completed")
        session.add(run)
        session.flush()
        return run

    async def _fake_person_sync(session, client_):
        run = HrPersonSync(status="completed")
        session.add(run)
        session.flush()
        return run

    monkeypatch.setattr(hr_review_module, "run_hierarchy_sync", AsyncMock(side_effect=_fake_hierarchy_sync))
    monkeypatch.setattr(hr_review_module, "run_person_sync", AsyncMock(side_effect=_fake_person_sync))

    from app.settings import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("HR_API_BASE_URL", "https://hr.example")
    monkeypatch.setenv("HR_API_KEY", "key")

    r = client.post("/api/admin/hr-sync/run-now", headers=headers)
    assert r.status_code == 200
    hr_review_module.run_hierarchy_sync.assert_called_once()
    hr_review_module.run_person_sync.assert_called_once()
    get_settings.cache_clear()
