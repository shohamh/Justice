from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.db.models import ExemptionRequest, ExemptionType, HierarchyNode, SoldierEnrollmentRequest, SystemSetting
from tests.helpers import create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _make_holding(session):
    node = HierarchyNode(level="division", name=f"holding_{_uid()}", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    session.flush()
    if session.get(SystemSetting, "system.holding_node_id") is None:
        session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    session.commit()
    return node


def _base(**overrides):
    return {
        "personal_number": f"pn_{_uid()}",
        "full_name": "Test Soldier",
        "password": "password-secure-1",
        "phone": "050-0000000",
        "email": None,
        "gender": "male",
        "is_officer": False,
        "rank": "טוראי",
        # Relative to today so a חובה-only rank never accidentally looks like it
        # outlived its own mandatory-service window as the real calendar advances.
        "enlistment_date": date.today() - timedelta(days=600),
        "mandatory_end_date": date.today() + timedelta(days=200),
        "discharge_date": date.today() + timedelta(days=600),
        "last_mitvahim_date": None,
        "last_alal_date": None,
        **overrides,
    }


def test_register_places_soldier_in_holding_node(admin_session):
    import sqlalchemy as sa
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    soldier = register(
        admin_session, invite_code=invite.code, requested_node_id=node.id,
        exemption_requests=[], personal_constraints=[], **_base()
    )
    admin_session.commit()

    assert soldier.hierarchy_node_id == holding.id
    req = admin_session.execute(
        sa.select(SoldierEnrollmentRequest).where(SoldierEnrollmentRequest.soldier_id == soldier.id)
    ).scalar_one()
    assert req.status == "pending"
    assert req.requested_node_id == node.id


def test_register_rejects_discharge_before_enlistment(admin_session):
    from app.services.registration import register, RegistrationError
    from app.services.invite_codes import create_invite_code

    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    with pytest.raises(RegistrationError, match="discharge_date"):
        register(
            admin_session, invite_code=invite.code, requested_node_id=node.id,
            exemption_requests=[], personal_constraints=[],
            **_base(enlistment_date=date(2024, 1, 1), discharge_date=date(2023, 1, 1)),
        )


def test_register_rejects_incompatible_rank_track(admin_session):
    # is_career is derived from mandatory_end_date/discharge_date (see
    # test_register_allows_keva_only_rank_once_mandatory_service_has_ended);
    # _base()'s mandatory_end_date is in the future, so is_career is still
    # False here, making a קבע-only rank like רסל incompatible.
    from app.services.registration import register, RegistrationError
    from app.services.invite_codes import create_invite_code

    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    with pytest.raises(RegistrationError, match="rank_track_incompatible"):
        register(
            admin_session, invite_code=invite.code, requested_node_id=node.id,
            exemption_requests=[], personal_constraints=[],
            **_base(rank="רסל"),
        )


def test_register_decrements_invite_code(admin_session):
    _make_holding(admin_session)
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=2, actor_id=None)
    admin_session.commit()
    register(admin_session, invite_code=invite.code, requested_node_id=node.id,
             exemption_requests=[], personal_constraints=[], **_base())
    admin_session.commit()
    admin_session.refresh(invite)
    assert invite.uses_left == 1


def test_register_exhausted_code_raises(admin_session):
    _make_holding(admin_session)
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    from app.services.invite_codes import create_invite_code, InviteCodeError
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=0, actor_id=None)
    admin_session.commit()
    with pytest.raises(InviteCodeError):
        register(admin_session, invite_code=invite.code, requested_node_id=node.id,
                 exemption_requests=[], personal_constraints=[], **_base())


def test_register_duplicate_personal_number_raises(admin_session):
    _make_holding(admin_session)
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    pn = f"dup_{_uid()}"
    create_soldier(admin_session, personal_number=pn)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register, RegistrationError
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()
    with pytest.raises(RegistrationError, match="personal_number"):
        register(admin_session, invite_code=invite.code, requested_node_id=node.id,
                 exemption_requests=[], personal_constraints=[], **_base(personal_number=pn))


# is_career is False here for two independent reasons: (1) rank "טוראי" is a
# חובה-only rank, so is_career short-circuits to False regardless of dates, and
# (2) mandatory_end_date (from _base()) is in the future anyway. This is NOT
# evidence that registration always hardcodes חובה — see derive_is_career for
# the actual date-based derivation this branch introduced.
def test_register_starts_as_chovah_while_mandatory_service_is_ongoing(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    soldier = register(
        admin_session, invite_code=invite.code, requested_node_id=node.id,
        exemption_requests=[], personal_constraints=[],
        **_base(discharge_date=date.today() + timedelta(days=365 * 5)),
    )
    admin_session.commit()

    assert soldier.is_career is False


def test_register_links_exemptions_to_enrollment(admin_session):
    import sqlalchemy as sa
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    # Create an exemption type to reference
    ex_type = ExemptionType(name=f"test_type_{_uid()}")
    admin_session.add(ex_type)
    admin_session.commit()

    soldier = register(
        admin_session, invite_code=invite.code, requested_node_id=node.id,
        exemption_requests=[{
            "exemption_type_id": ex_type.id,
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 12, 31),
            "reason": "test reason",
        }],
        personal_constraints=[], **_base()
    )
    admin_session.commit()

    enrollment_req = admin_session.execute(
        sa.select(SoldierEnrollmentRequest).where(SoldierEnrollmentRequest.soldier_id == soldier.id)
    ).scalar_one()
    exemption = admin_session.execute(
        sa.select(ExemptionRequest).where(ExemptionRequest.soldier_id == soldier.id)
    ).scalar_one()

    assert exemption.enrollment_request_id == enrollment_req.id
    assert exemption.status == "pending_commander"


def test_register_rejects_commander_exemption_type(admin_session):
    """A soldier self-registering must not be able to request a commander-exemption
    (פטור פיקודי) type — that path is gated to authorized commanders/duty-managers via
    grant_commander_exemption, not the self-service registration/request flow."""
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import RegistrationError, register
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    commander_type = ExemptionType(name=f"commander_type_{_uid()}", is_commander_exemption=True)
    admin_session.add(commander_type)
    admin_session.commit()

    with pytest.raises(RegistrationError, match="commander_exemption_not_requestable"):
        register(
            admin_session, invite_code=invite.code, requested_node_id=node.id,
            exemption_requests=[{
                "exemption_type_id": commander_type.id,
                "start_date": date(2024, 1, 1),
                "end_date": None,
                "reason": None,
            }],
            personal_constraints=[], **_base()
        )


def test_register_rejects_unknown_exemption_type(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import RegistrationError, register
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    with pytest.raises(RegistrationError, match="exemption_type_not_found"):
        register(
            admin_session, invite_code=invite.code, requested_node_id=node.id,
            exemption_requests=[{
                "exemption_type_id": uuid.uuid4(),
                "start_date": date(2024, 1, 1),
                "end_date": None,
                "reason": None,
            }],
            personal_constraints=[], **_base()
        )


def test_register_rejects_bad_exemption_date_range(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import RegistrationError, register
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    ex_type = ExemptionType(name=f"test_type_{_uid()}")
    admin_session.add(ex_type)
    admin_session.commit()

    with pytest.raises(RegistrationError, match="bad_date_range"):
        register(
            admin_session, invite_code=invite.code, requested_node_id=node.id,
            exemption_requests=[{
                "exemption_type_id": ex_type.id,
                "start_date": date(2024, 12, 31),
                "end_date": date(2024, 1, 1),
                "reason": None,
            }],
            personal_constraints=[], **_base()
        )


def test_register_allows_keva_only_rank_once_mandatory_service_has_ended(admin_session):
    """Regression: registration used to hardcode is_career=False, so a soldier
    whose mandatory service already ended (mandatory_end_date in the past,
    rank is קבע-only) was incorrectly rejected as a track mismatch."""
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    soldier = register(
        admin_session, invite_code=invite.code, requested_node_id=node.id,
        exemption_requests=[], personal_constraints=[],
        **_base(
            rank="רסן",
            mandatory_end_date=date.today() - timedelta(days=30),
            discharge_date=date.today() + timedelta(days=365 * 3),
        ),
    )
    admin_session.commit()

    assert soldier.is_career is True
    assert soldier.rank == "רסן"


def test_register_rejects_discharge_date_in_past(admin_session):
    from app.services.registration import register, RegistrationError
    from app.services.invite_codes import create_invite_code

    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    with pytest.raises(RegistrationError, match="discharge_date_in_past"):
        register(
            admin_session, invite_code=invite.code, requested_node_id=node.id,
            exemption_requests=[], personal_constraints=[],
            **_base(discharge_date=date.today() - timedelta(days=1)),
        )


def test_register_derives_bahad1_graduate_from_rank(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=2, actor_id=None)
    admin_session.commit()

    # סרן and קאב are קבע-only ranks (see _KEVA_ONLY_TRACK_RANKS in
    # eligibility.py), so mandatory_end_date must already be in the past for
    # derive_is_career to land on True and pass rank/track compatibility —
    # otherwise register() raises rank_track_incompatible before we ever get
    # to check the derived bahad1_graduate value.
    officer = register(
        admin_session, invite_code=invite.code, requested_node_id=node.id,
        exemption_requests=[], personal_constraints=[],
        **_base(
            rank="סרן", is_officer=True,
            mandatory_end_date=date.today() - timedelta(days=30),
            discharge_date=date.today() + timedelta(days=365 * 3),
        ),
    )
    admin_session.commit()
    assert officer.bahad1_graduate is True

    invite2 = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()
    kaab_officer = register(
        admin_session, invite_code=invite2.code, requested_node_id=node.id,
        exemption_requests=[], personal_constraints=[],
        **_base(
            rank="קאב", is_officer=True,
            mandatory_end_date=date.today() - timedelta(days=30),
            discharge_date=date.today() + timedelta(days=365 * 3),
        ),
    )
    admin_session.commit()
    assert kaab_officer.bahad1_graduate is False
