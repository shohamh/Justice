from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.models import (
    ScoreProjectionDirtyBucket,
    SoldierQuarterScoreProjection,
)
from app.services.score_projection import backfill_score_projection
from app.services.score_projection_reconciliation import revalidate_score_projection
from app.services.tests.test_score_projection import _seed_projection_scenario


def _corrupt_one_bucket(admin_session):
    """Overwrite a typed partition row with values that violate its fingerprint."""
    stale_row = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.duty_type_id.is_not(None)
        )
    ).scalars().first()
    assert stale_row is not None
    stale_row.duty_score = Decimal("123.456789")
    stale_row.source_fingerprint = {"corrupted": True}
    admin_session.flush()
    return stale_row


def test_revalidate_repairs_unmarked_corruption_and_advances_cursor(
    admin_session,
):
    scenario = _seed_projection_scenario(admin_session)
    backfill_score_projection(admin_session)
    admin_session.flush()

    stale_row = _corrupt_one_bucket(admin_session)

    stats = revalidate_score_projection(admin_session, batch_size=500)

    assert stats["validated"] > 0
    assert stats["violations"] >= 1
    repaired_rows = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == stale_row.soldier_id,
            SoldierQuarterScoreProjection.quarter_start == stale_row.quarter_start,
        )
    ).scalars().all()
    assert repaired_rows
    assert all(row.source_fingerprint != {"corrupted": True} for row in repaired_rows)

    # Cursor advanced to the last validated bucket.
    from app.db.models import ScoreProjectionState

    state_row = admin_session.execute(select(ScoreProjectionState)).scalar_one()
    assert state_row.revalidated_after_soldier_id is not None


def test_revalidate_repairs_quarter_totals_of_repaired_buckets(
    admin_session,
):
    scenario = _seed_projection_scenario(admin_session)
    backfill_score_projection(admin_session)
    admin_session.flush()

    # Corrupt every typed row in Q3 so its quarter total becomes unprovable.
    rows = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.quarter_start == date(2026, 7, 1),
            SoldierQuarterScoreProjection.duty_type_id.is_not(None),
        )
    ).scalars().all()
    assert rows
    for row in rows:
        row.source_fingerprint = {"corrupted": True}
    admin_session.flush()

    stats = revalidate_score_projection(admin_session, batch_size=1000)
    assert stats["violations"] >= 1

    remaining_bad = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.quarter_start == date(2026, 7, 1),
            SoldierQuarterScoreProjection.source_fingerprint == {"corrupted": True},
        )
    ).scalars().all()
    assert remaining_bad == []
