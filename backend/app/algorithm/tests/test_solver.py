from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.algorithm.model import build_model
from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, SolverSettings


def test_build_model_basic():
    soldier_id = uuid4()
    duty_id = uuid4()
    soldiers = [
        SoldierInput(
            id=soldier_id,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=100,
        )
    ]
    duties = [
        DutyBlock(
            id=duty_id,
            duty_type_id=uuid4(),
            duty_location_id=uuid4(),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            score_per_day=Decimal("1.00"),
        )
    ]
    existing: list[ExistingAssignment] = []
    settings = SolverSettings()
    model = build_model(soldiers=soldiers, duties=duties, existing=existing, settings=settings)
    assert model is not None
