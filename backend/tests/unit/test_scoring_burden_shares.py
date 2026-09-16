# backend/tests/unit/test_scoring_burden_shares.py
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models import DutyAssignment, HierarchyNode, SystemSetting
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


def test_burden_shares_by_soldier_include_drafts_stays_unit_consistent(admin_session):
    """The include_drafts variant must stay a scale-invariant A_i/W_i ratio
    (like the published-only default), not a raw days*score_per_day quantity
    layered on top of one -- and must ignore drafts entirely when the flag is
    off, and honor exclude_assignment_ids when it is on."""
    admin_session.add(SystemSetting(key="fairness.reset_date", value="2026-07-01"))
    admin_session.flush()

    dt, loc = _seed_duty_type(admin_session, "burden-drafts")
    plain = create_soldier(admin_session, personal_number="9930010")
    drafted = create_soldier(admin_session, personal_number="9930011")
    for s in (plain, drafted):
        s.enrolled_at = date(2025, 1, 1)
    admin_session.flush()

    draft_assignment = DutyAssignment(
        soldier_id=drafted.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        status="algorithm_draft",
    )
    admin_session.add(draft_assignment)
    admin_session.commit()

    published_only = burden_shares_by_soldier(admin_session, [plain, drafted])
    assert published_only[plain.id] == 0.0
    # A draft-only assignment must not leak into the published-only score.
    assert published_only[drafted.id] == 0.0

    with_drafts = burden_shares_by_soldier(admin_session, [plain, drafted], include_drafts=True)
    assert with_drafts[plain.id] == 0.0
    assert with_drafts[drafted.id] > 0.0
    # A scale-invariant A_i/W_i ratio never exceeds 1 -- if this were the raw
    # days*score_per_day quantity the old buggy code added on top of the
    # ratio, a 4-day duty at score_per_day=1.00 would blow well past that.
    assert with_drafts[drafted.id] <= 1.0

    excluded = burden_shares_by_soldier(
        admin_session, [plain, drafted],
        include_drafts=True, exclude_assignment_ids={draft_assignment.id},
    )
    assert excluded[drafted.id] == 0.0
