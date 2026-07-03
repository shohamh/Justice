from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.db.models import DutyType, Soldier
from app.services.hierarchy import create_node
from app.services.potential import compute_potential


def _make_soldier(session, *, node_id, rank="טוראי", left_at=None, gender="m"):
    s = Soldier(
        personal_number=str(uuid.uuid4())[:8],
        full_name="Test Soldier",
        password_hash="x",
        hierarchy_node_id=node_id,
        rank=rank,
        gender=gender,
        left_at=left_at,
    )
    session.add(s)
    session.flush()
    return s


def test_compute_potential_counts_eligible_soldiers(app_session):
    node = create_node(app_session, level="team", name="Test Co", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    _make_soldier(app_session, node_id=node.id)
    _make_soldier(app_session, node_id=node.id)
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))

    assert result.raw_eligible_count == 2
    assert result.final_potential == 2
