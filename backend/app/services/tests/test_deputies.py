from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.db.models import RoleDeputy
from app.services.deputies import (
    DeputyError,
    create_deputy,
    list_active_deputies_for,
    list_deputies,
    revoke_deputy,
)
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_create_deputy_for_a_real_commander_succeeds(admin_session):
    principal = create_soldier(admin_session, personal_number=f"a_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"b_{_uid()}")

    entry = create_deputy(
        admin_session, principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today() + timedelta(days=7), actor_id=principal.id,
    )
    admin_session.commit()

    assert entry.principal_id == principal.id
    assert entry.deputy_id == deputy.id
    assert entry.role == "commander"


def test_create_deputy_rejects_principal_who_lacks_the_role(admin_session):
    principal = create_soldier(admin_session, personal_number=f"c_{_uid()}")  # plain soldier
    deputy = create_soldier(admin_session, personal_number=f"d_{_uid()}")

    with pytest.raises(DeputyError, match="principal_lacks_role"):
        create_deputy(
            admin_session, principal_id=principal.id, deputy_id=deputy.id, role="commander",
            start_date=date.today(), end_date=date.today(), actor_id=principal.id,
        )


def test_create_deputy_rejects_end_before_start(admin_session):
    principal = create_soldier(admin_session, personal_number=f"e_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"f_{_uid()}")

    with pytest.raises(DeputyError, match="invalid_date_range"):
        create_deputy(
            admin_session, principal_id=principal.id, deputy_id=deputy.id, role="commander",
            start_date=date.today() + timedelta(days=1), end_date=date.today(), actor_id=principal.id,
        )


def test_create_deputy_rejects_self_deputizing(admin_session):
    principal = create_soldier(admin_session, personal_number=f"g_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)

    with pytest.raises(DeputyError, match="cannot_deputize_self"):
        create_deputy(
            admin_session, principal_id=principal.id, deputy_id=principal.id, role="commander",
            start_date=date.today(), end_date=date.today(), actor_id=principal.id,
        )


def test_create_deputy_rejects_recursion(admin_session):
    """A soldier who is themselves currently an active deputy for `role`
    cannot be named as a principal for a new deputy grant (no sub-deputies)."""
    grandparent = create_soldier(admin_session, personal_number=f"h_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=grandparent.id)
    parent = create_soldier(admin_session, personal_number=f"i_{_uid()}")
    create_deputy(
        admin_session, principal_id=grandparent.id, deputy_id=parent.id, role="commander",
        start_date=date.today(), end_date=date.today() + timedelta(days=10), actor_id=grandparent.id,
    )
    admin_session.commit()
    child = create_soldier(admin_session, personal_number=f"j_{_uid()}")

    with pytest.raises(DeputyError, match="cannot_deputize_a_deputy"):
        create_deputy(
            admin_session, principal_id=parent.id, deputy_id=child.id, role="commander",
            start_date=date.today(), end_date=date.today(), actor_id=grandparent.id,
        )


def test_create_deputy_rejects_recursion_even_without_date_overlap(admin_session):
    """Gap scenario: a soldier's existing deputy grant ends TODAY (so
    is_commander(soldier) is True today), and someone attempts to name that
    same soldier as PRINCIPAL for a brand-new deputy grant with a FUTURE
    window that does NOT overlap their existing grant's window. This must
    still be rejected — an overlap-only check would wrongly allow it,
    producing a sub-deputy with no real permissions once the existing grant
    ends."""
    grandparent = create_soldier(admin_session, personal_number=f"u_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=grandparent.id)
    parent = create_soldier(admin_session, personal_number=f"v_{_uid()}")
    create_deputy(
        admin_session, principal_id=grandparent.id, deputy_id=parent.id, role="commander",
        start_date=date.today() - timedelta(days=5), end_date=date.today(), actor_id=grandparent.id,
    )
    admin_session.commit()
    child = create_soldier(admin_session, personal_number=f"w_{_uid()}")

    with pytest.raises(DeputyError, match="cannot_deputize_a_deputy"):
        create_deputy(
            admin_session, principal_id=parent.id, deputy_id=child.id, role="commander",
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + timedelta(days=37),
            actor_id=grandparent.id,
        )


def test_create_deputy_allows_one_deputy_for_multiple_principals(admin_session):
    p1 = create_soldier(admin_session, personal_number=f"k_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n1_{_uid()}", commander_id=p1.id)
    p2 = create_soldier(admin_session, personal_number=f"l_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n2_{_uid()}", commander_id=p2.id)
    deputy = create_soldier(admin_session, personal_number=f"m_{_uid()}")

    create_deputy(
        admin_session, principal_id=p1.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(), actor_id=p1.id,
    )
    admin_session.commit()
    entry2 = create_deputy(
        admin_session, principal_id=p2.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(), actor_id=p2.id,
    )
    admin_session.commit()

    assert entry2.principal_id == p2.id


def test_list_deputies_returns_all_grants_for_a_principal(admin_session):
    principal = create_soldier(admin_session, personal_number=f"n_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    d1 = create_soldier(admin_session, personal_number=f"o_{_uid()}")
    d2 = create_soldier(admin_session, personal_number=f"p_{_uid()}")
    create_deputy(
        admin_session, principal_id=principal.id, deputy_id=d1.id, role="commander",
        start_date=date.today(), end_date=date.today(), actor_id=principal.id,
    )
    create_deputy(
        admin_session, principal_id=principal.id, deputy_id=d2.id, role="commander",
        start_date=date.today() + timedelta(days=30), end_date=date.today() + timedelta(days=37),
        actor_id=principal.id,
    )
    admin_session.commit()

    grants = list_deputies(admin_session, principal_id=principal.id)
    assert {g.deputy_id for g in grants} == {d1.id, d2.id}


def test_list_active_deputies_for_only_returns_currently_active_grants(admin_session):
    principal = create_soldier(admin_session, personal_number=f"q_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"r_{_uid()}")
    create_deputy(
        admin_session, principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=10),
        actor_id=principal.id,
    )
    admin_session.commit()

    assert list_active_deputies_for(admin_session, deputy_id=deputy.id) == []
    assert len(list_active_deputies_for(
        admin_session, deputy_id=deputy.id, today=date.today() + timedelta(days=7)
    )) == 1


def test_revoke_deputy_deletes_the_grant(admin_session):
    principal = create_soldier(admin_session, personal_number=f"s_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"t_{_uid()}")
    entry = create_deputy(
        admin_session, principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(), actor_id=principal.id,
    )
    admin_session.commit()

    revoke_deputy(admin_session, deputy_grant_id=entry.id, actor_id=principal.id)
    admin_session.commit()

    assert admin_session.get(RoleDeputy, entry.id) is None


def test_revoke_deputy_raises_for_unknown_grant(admin_session):
    with pytest.raises(DeputyError, match="deputy_grant_not_found"):
        revoke_deputy(admin_session, deputy_grant_id=uuid.uuid4(), actor_id=None)
