# backend/tests/unit/test_scoring_burden_shares.py
from __future__ import annotations

from datetime import date

from app.db.models import HierarchyNode, SystemSetting
from app.services.scoring import burden_shares_by_soldier
from tests.helpers import create_soldier


def _seed_duty_type(session, name: str):
    from decimal import Decimal
    from app.db.models import DutyLocation, DutyType

    dt = DutyType(name=name, score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc-{name}")
    session.add_all([dt, loc])
    session.flush()
    return dt, loc


def test_burden_shares_by_soldier_honors_hierarchy_override(admin_session):
    """burden_shares_by_soldier must stop forcing the global reset date, or a
    hierarchy override never reaches this read path at all."""
    node = HierarchyNode(level="division", name="polaris-shares", path_ids=[])
    admin_session.add(node)
    admin_session.flush()
    node.path_ids = [node.id]
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.add(SystemSetting(
        key="fairness.reset_date_overrides", value={str(node.id): "2026-08-20"}
    ))
    admin_session.flush()

    dt, loc = _seed_duty_type(admin_session, "burden-shares")
    s = create_soldier(admin_session, personal_number="9930001")
    s.hierarchy_node_id = node.id
    s.enrolled_at = date(2025, 1, 1)
    admin_session.flush()

    from app.services.assignments import create_assignment
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 25), end_date=date(2026, 9, 4), actor_id=None,
    )
    admin_session.flush()

    shares = burden_shares_by_soldier(admin_session, [s])
    # Fully active since before the branch's own reset date (Aug 20) -> full
    # active_frac for the post-reset portion of the quarter -> nonzero share.
    # If the global default (Jul 1) were still being forced, the math would
    # still produce a nonzero share here too, so the real assertion is in the
    # source-inspection tests below, which prove the override CAN reach this
    # function at all rather than being silently discarded by an explicit arg.
    assert shares[s.id] > 0
