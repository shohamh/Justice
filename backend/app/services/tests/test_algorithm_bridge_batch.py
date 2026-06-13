"""Tests for batch_results post-processing in algorithm_bridge."""
import uuid
from datetime import date

from app.algorithm.types import (
    Assignment, BatchResult, BatchShiftFill, SolverResult,
)
from app.services.algorithm_bridge import _postprocess_batch_results


def test_postprocess_aggregates_by_shift():
    """Multiple blocks mapping to same shift are aggregated into one BatchShiftFill."""
    shift_id = uuid.uuid4()
    block_a = uuid.uuid4()
    block_b = uuid.uuid4()
    block_to_shift = {block_a: shift_id, block_b: shift_id}

    br = BatchResult(
        batch_index=0,
        component_index=0,
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        duty_count=2,
        soldier_count=1,
        assigned_count=2,
        unassigned_count=0,
        outcome="OPTIMAL",
        relaxations=[],
        wall_time_seconds=0.1,
        shifts=[
            BatchShiftFill(shift_id=block_a, required_count=1, assigned_count=1),
            BatchShiftFill(shift_id=block_b, required_count=1, assigned_count=1),
        ],
    )

    processed = _postprocess_batch_results([br], block_to_shift)

    assert len(processed) == 1
    result_br = processed[0]
    assert len(result_br.shifts) == 1
    sf = result_br.shifts[0]
    assert sf.shift_id == shift_id
    assert sf.required_count == 2
    assert sf.assigned_count == 2


def test_postprocess_partial_fill():
    """Partially filled shifts are correctly aggregated."""
    shift_id = uuid.uuid4()
    block_a = uuid.uuid4()
    block_b = uuid.uuid4()
    block_to_shift = {block_a: shift_id, block_b: shift_id}

    br = BatchResult(
        batch_index=0,
        component_index=0,
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        duty_count=2,
        soldier_count=1,
        assigned_count=1,
        unassigned_count=1,
        outcome="FEASIBLE",
        relaxations=[],
        wall_time_seconds=0.1,
        shifts=[
            BatchShiftFill(shift_id=block_a, required_count=1, assigned_count=1),
            BatchShiftFill(shift_id=block_b, required_count=1, assigned_count=0),
        ],
    )

    processed = _postprocess_batch_results([br], block_to_shift)

    assert len(processed[0].shifts) == 1
    sf = processed[0].shifts[0]
    assert sf.required_count == 2
    assert sf.assigned_count == 1
