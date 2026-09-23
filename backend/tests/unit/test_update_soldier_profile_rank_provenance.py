from __future__ import annotations

from app.services.soldiers import update_soldier_profile
from tests.helpers import create_soldier


def test_update_soldier_profile_sets_rank_last_set_by_manual(app_session) -> None:
    """The admin/DM manual-edit path (update_soldier_profile) is the other
    writer of Soldier.rank besides the rank_advancement_worker -- it must
    stamp rank_last_set_by="manual" so Task 3's conflict-detection logic can
    tell a manual override apart from a worker-driven promotion."""
    s = create_soldier(app_session, personal_number="2000001")
    s.rank = "טוראי"
    app_session.commit()

    update_soldier_profile(app_session, soldier=s, fields={"rank": "רבט"}, actor_id=None)

    assert s.rank == "רבט"
    assert s.rank_last_set_by == "manual"


def test_update_soldier_profile_leaves_rank_last_set_by_unset_when_rank_not_edited(app_session) -> None:
    """A PATCH that doesn't touch `rank` at all must not fire the provenance
    write -- e.g. editing only the phone number of a worker-promoted soldier
    must not silently reclassify that soldier's rank as manually set."""
    s = create_soldier(app_session, personal_number="2000002")
    s.rank = "טוראי"
    s.rank_last_set_by = "worker"
    app_session.commit()

    update_soldier_profile(app_session, soldier=s, fields={"phone": "0501234567"}, actor_id=None)

    assert s.rank_last_set_by == "worker"
