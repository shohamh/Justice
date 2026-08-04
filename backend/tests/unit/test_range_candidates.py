from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeAssignment, RangeType
from app.services.range_auto_assign import rank_candidates
from app.services.ranges import add_range_assignment, create_range_event
from tests.helpers import create_node, create_soldier


def _event(session: Session, *, required_count: int = 2, reserve_count: int = 1):
    node = create_node(session, level="branch", name="candidates")
    session.add(DutyType(name="weapon candidates", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    session.flush()
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="range",
        required_count=required_count, reserve_count=reserve_count,
    )
    return node, event


def test_ranks_available_soldiers_and_excludes_already_assigned(app_session: Session) -> None:
    node, event = _event(app_session)
    already = create_soldier(app_session, personal_number="cand-assigned", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=already.id, is_reserve=False)
    open_candidate = create_soldier(app_session, personal_number="cand-open", hierarchy_node_id=node.id)

    ranked = rank_candidates(app_session, event=event)

    ranked_ids = {c.soldier.id for c in ranked}
    assert already.id not in ranked_ids
    assert open_candidate.id in ranked_ids
    assert all(not c.blocked for c in ranked)


def test_marks_exempt_soldier_as_blocked_instead_of_excluding(app_session: Session) -> None:
    node, event = _event(app_session)
    soldier = create_soldier(app_session, personal_number="cand-exempt", hierarchy_node_id=node.id)

    from app.db.models import SoldierRangeQualification
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=event.date + timedelta(days=365), source_range_event_id=None, source_range_assignment_id=None,
    ))
    app_session.commit()

    ranked = rank_candidates(app_session, event=event)
    mine = next(c for c in ranked if c.soldier.id == soldier.id)
    assert mine.blocked is False
    assert mine.reason_code == "qualified"


def test_does_not_write_any_assignment_rows(app_session: Session) -> None:
    node, event = _event(app_session)
    create_soldier(app_session, personal_number="cand-readonly", hierarchy_node_id=node.id)

    rank_candidates(app_session, event=event)

    remaining = app_session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
    ).scalars().all()
    assert remaining == []
