from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeType, SoldierRangeQualification
from app.services.settings_loader import set_setting
from app.services.soldier_range_status import list_relevant_range_statuses
from tests.helpers import create_node, create_soldier


def _enable_mitvachim(session: Session) -> None:
    set_setting(session, "mitvachim.enabled", True, actor_id=None)


def test_returns_one_status_per_relevant_required_range_type(app_session: Session) -> None:
    node = create_node(app_session, level="team", name="range-status-team-1")
    soldier = create_soldier(app_session, personal_number="rs-001", hierarchy_node_id=node.id)
    _enable_mitvachim(app_session)
    app_session.add(DutyType(
        name="alal-duty-1", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.commit()

    statuses = list_relevant_range_statuses(app_session, soldier=soldier)

    assert len(statuses) == 1
    assert statuses[0].required_range_type == RangeType.alal
    assert statuses[0].eligible is False
    assert statuses[0].last_qualification_type is None


def test_reports_current_qualification_as_eligible(app_session: Session) -> None:
    node = create_node(app_session, level="team", name="range-status-team-2")
    soldier = create_soldier(app_session, personal_number="rs-002", hierarchy_node_id=node.id)
    _enable_mitvachim(app_session)
    app_session.add(DutyType(
        name="alal-duty-2", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.alal,
        valid_until=date.today() + timedelta(days=30),
    ))
    app_session.commit()

    statuses = list_relevant_range_statuses(app_session, soldier=soldier)

    assert statuses[0].eligible is True
    assert statuses[0].qualification_source == "current_qualification"


def test_reports_profile_range_date_as_eligible(app_session: Session) -> None:
    node = create_node(app_session, level="team", name="range-status-team-profile")
    soldier = create_soldier(app_session, personal_number="rs-profile-001", hierarchy_node_id=node.id)
    soldier.last_mitvahim_date = date.today() - timedelta(days=1)
    _enable_mitvachim(app_session)
    app_session.add(DutyType(
        name="laser-duty-profile", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    ))
    app_session.commit()

    statuses = list_relevant_range_statuses(app_session, soldier=soldier)

    assert statuses[0].eligible is True


def test_returns_empty_when_soldier_has_no_relevant_duty_types(app_session: Session) -> None:
    node = create_node(app_session, level="team", name="range-status-team-3")
    soldier = create_soldier(app_session, personal_number="rs-003", hierarchy_node_id=node.id)
    _enable_mitvachim(app_session)
    app_session.commit()

    statuses = list_relevant_range_statuses(app_session, soldier=soldier)

    assert statuses == []
