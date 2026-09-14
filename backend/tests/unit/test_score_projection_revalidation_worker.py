import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.score_projection_revalidation_worker import (
    _projection_tick,
    run_score_projection_revalidation_worker,
)


def test_projection_tick_resumes_incomplete_backfill_without_revalidation():
    session = MagicMock()
    session.get.return_value = SimpleNamespace(backfill_complete=False)
    completed_state = SimpleNamespace(backfill_complete=True, resume_after_quarter_start=None)

    with (
        patch("app.score_projection_revalidation_worker.backfill_score_projection", return_value=completed_state) as backfill,
        patch("app.score_projection_revalidation_worker.revalidate_score_projection") as revalidate,
    ):
        assert _projection_tick(session) is True

    backfill.assert_called_once()
    revalidate.assert_not_called()
    session.commit.assert_called_once()


def test_projection_tick_revalidates_completed_projection():
    session = MagicMock()
    session.get.return_value = SimpleNamespace(backfill_complete=True)

    with (
        patch("app.score_projection_revalidation_worker.backfill_score_projection") as backfill,
        patch(
            "app.score_projection_revalidation_worker.revalidate_score_projection",
            return_value={"validated": 1, "violations": 0, "repaired": 0},
        ) as revalidate,
    ):
        assert _projection_tick(session) is True

    backfill.assert_not_called()
    revalidate.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_worker_runs_maintenance_immediately_after_startup():
    async def run_in_thread(function):
        return function()

    with (
        patch("app.score_projection_revalidation_worker._maintenance_tick", return_value=True) as tick,
        patch(
            "app.score_projection_revalidation_worker.asyncio.to_thread",
            side_effect=run_in_thread,
        ),
        patch(
            "app.score_projection_revalidation_worker.asyncio.sleep",
            side_effect=asyncio.CancelledError,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_score_projection_revalidation_worker()

    tick.assert_called_once()
