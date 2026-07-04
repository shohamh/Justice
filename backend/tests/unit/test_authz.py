from app.auth import authz
from tests.helpers import create_node, create_soldier


def _roots(session, user):
    return authz.scope_root_ids(session, user)


def _caps(session, user):
    return authz.is_commander(session, user.id), authz.is_duty_manager(session, user.id)


def test_admin_can_everything_globally(admin_session):
    admin = create_soldier(admin_session, personal_number="7000001", role="admin")
    d = create_node(admin_session, level="department", name="d")
    is_cmd, is_dm = _caps(admin_session, admin)
    assert authz.can(
        admin, authz.Action.SOLDIER_CREATE, target_node=d, roots=_roots(admin_session, admin),
        is_commander=is_cmd, is_duty_manager=is_dm,
    )
    assert authz.can(
        admin, authz.Action.HIERARCHY_MANAGE, target_node=d, roots=_roots(admin_session, admin),
        is_commander=is_cmd, is_duty_manager=is_dm,
    )


def test_duty_manager_scoped_to_own_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    dm = create_soldier(
        admin_session, personal_number="7000002", role="duty_manager", hierarchy_node_id=b.id
    )
    roots = _roots(admin_session, dm)
    is_cmd, is_dm = _caps(admin_session, dm)
    assert authz.can(dm, authz.Action.SOLDIER_CREATE, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert not authz.can(dm, authz.Action.SOLDIER_CREATE, target_node=other, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_read_only_in_commanded_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7000003", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert authz.can(cmd, authz.Action.SOLDIER_READ, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert authz.can(cmd, authz.Action.HIERARCHY_READ, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert not authz.can(cmd, authz.Action.SOLDIER_CREATE, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_plain_soldier_has_no_management(admin_session):
    d = create_node(admin_session, level="department", name="d")
    s = create_soldier(
        admin_session, personal_number="7000004", role="soldier", hierarchy_node_id=d.id
    )
    roots = _roots(admin_session, s)
    assert roots == set()
    is_cmd, is_dm = _caps(admin_session, s)
    assert not authz.can(s, authz.Action.SOLDIER_READ, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_can_grant_and_read_exemptions_in_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    cmd = create_soldier(admin_session, personal_number="7100001", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert authz.can(cmd, authz.Action.EXEMPTION_GRANT, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert authz.can(cmd, authz.Action.EXEMPTION_READ, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert not authz.can(cmd, authz.Action.EXEMPTION_GRANT, target_node=other, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_duty_manager_can_grant_exemptions_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    dm = create_soldier(
        admin_session, personal_number="7100002", role="duty_manager", hierarchy_node_id=b.id
    )
    roots = _roots(admin_session, dm)
    is_cmd, is_dm = _caps(admin_session, dm)
    assert authz.can(dm, authz.Action.EXEMPTION_GRANT, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_plain_soldier_cannot_grant_exemptions(admin_session):
    d = create_node(admin_session, level="department", name="d")
    s = create_soldier(
        admin_session, personal_number="7100003", role="soldier", hierarchy_node_id=d.id
    )
    roots = _roots(admin_session, s)
    is_cmd, is_dm = _caps(admin_session, s)
    assert not authz.can(s, authz.Action.EXEMPTION_GRANT, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_duty_manager_can_manage_assignments_and_scores_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="d-s4")
    b = create_node(admin_session, level="branch", name="b-s4", parent=d)
    other = create_node(admin_session, level="department", name="other-s4")
    dm = create_soldier(
        admin_session, personal_number="7400001", role="duty_manager", hierarchy_node_id=b.id
    )
    roots = _roots(admin_session, dm)
    is_cmd, is_dm = _caps(admin_session, dm)
    assert authz.can(dm, authz.Action.ASSIGNMENT_MANAGE, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert authz.can(dm, authz.Action.SCORE_ADJUST, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert not authz.can(dm, authz.Action.ASSIGNMENT_MANAGE, target_node=other, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_cannot_manage_assignments(admin_session):
    d = create_node(admin_session, level="department", name="d-s4b")
    b = create_node(admin_session, level="branch", name="b-s4b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7400002", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert not authz.can(cmd, authz.Action.ASSIGNMENT_MANAGE, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert not authz.can(cmd, authz.Action.SCORE_ADJUST, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_plain_soldier_cannot_manage_assignments(admin_session):
    d = create_node(admin_session, level="department", name="d-s4c")
    s = create_soldier(
        admin_session, personal_number="7400003", role="soldier", hierarchy_node_id=d.id
    )
    roots = _roots(admin_session, s)
    is_cmd, is_dm = _caps(admin_session, s)
    assert not authz.can(s, authz.Action.ASSIGNMENT_MANAGE, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_dual_role_soldier_keeps_both_capabilities(admin_session):
    """A soldier who commands node A and is DM of node B keeps DM_SCOPE_MANAGE over A
    and DM actions over B simultaneously — neither capability clobbers the other."""
    from app.db.models import DutyManagerScope

    a = create_node(admin_session, level="department", name="dual-a")
    b = create_node(admin_session, level="department", name="dual-b")
    dual = create_soldier(admin_session, personal_number="7500001", role="commander")
    dual.rank = "רסן"
    a.commander_id = dual.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    admin_session.commit()

    roots = _roots(admin_session, dual)
    is_cmd, is_dm = _caps(admin_session, dual)
    assert is_cmd and is_dm
    assert authz.can(dual, authz.Action.DM_SCOPE_MANAGE, target_node=a, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert authz.can(dual, authz.Action.ASSIGNMENT_MANAGE, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert authz.can(dual, authz.Action.ALGORITHM_RUN, target_node=None, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


# ── can_see_private ──────────────────────────────────────────────────────────


def test_can_see_private_self(admin_session):
    d = create_node(admin_session, level="department", name="csp-d1")
    s = create_soldier(admin_session, personal_number="csp001", hierarchy_node_id=d.id)
    assert authz.can_see_private(admin_session, viewer=s, target=s)


def test_admin_cannot_see_private(admin_session):
    admin = create_soldier(admin_session, personal_number="csp-adm001", role="admin")
    target = create_soldier(admin_session, personal_number="csp002")
    assert not authz.can_see_private(admin_session, viewer=admin, target=target)


def test_dm_in_scope_can_see_private(admin_session):
    d = create_node(admin_session, level="department", name="csp-d2")
    dm = create_soldier(admin_session, personal_number="csp-dm001", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="csp003", hierarchy_node_id=d.id)
    assert authz.can_see_private(admin_session, viewer=dm, target=target)


def test_dm_out_of_scope_cannot_see_private(admin_session):
    d = create_node(admin_session, level="department", name="csp-d3")
    other = create_node(admin_session, level="department", name="csp-d4")
    dm = create_soldier(admin_session, personal_number="csp-dm002", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="csp004", hierarchy_node_id=other.id)
    assert not authz.can_see_private(admin_session, viewer=dm, target=target)


def test_commander_in_chain_can_see_private(admin_session):
    d = create_node(admin_session, level="department", name="csp-d5")
    cmd = create_soldier(admin_session, personal_number="csp-cmd001", role="commander")
    d.commander_id = cmd.id
    admin_session.flush()
    target = create_soldier(admin_session, personal_number="csp005", hierarchy_node_id=d.id)
    assert authz.can_see_private(admin_session, viewer=cmd, target=target)


def test_admin_who_is_also_commander_can_see_private_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="csp-d7")
    admin_cmd = create_soldier(admin_session, personal_number="csp-adm002", role="admin")
    d.commander_id = admin_cmd.id
    admin_session.flush()
    target = create_soldier(admin_session, personal_number="csp008", hierarchy_node_id=d.id)
    assert authz.can_see_private(admin_session, viewer=admin_cmd, target=target)


def test_plain_soldier_cannot_see_peer_private(admin_session):
    d = create_node(admin_session, level="department", name="csp-d6")
    viewer = create_soldier(admin_session, personal_number="csp006", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="csp007", hierarchy_node_id=d.id)
    assert not authz.can_see_private(admin_session, viewer=viewer, target=target)


def test_dm_can_decide_military_license_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="mdl-d1")
    dm = create_soldier(admin_session, personal_number="7600001", role="duty_manager", hierarchy_node_id=d.id)
    roots = _roots(admin_session, dm)
    is_cmd, is_dm = _caps(admin_session, dm)
    assert authz.can(dm, authz.Action.MILITARY_LICENSE_DECIDE, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_below_rasan_cannot_decide_military_license(admin_session):
    d = create_node(admin_session, level="department", name="mdl-d2")
    cmd = create_soldier(admin_session, personal_number="7600002", role="commander")
    cmd.rank = "סרן"
    d.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert not authz.can(cmd, authz.Action.MILITARY_LICENSE_DECIDE, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_rasan_and_above_can_decide_military_license_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="mdl-d3")
    cmd = create_soldier(admin_session, personal_number="7600003", role="commander")
    cmd.rank = "רסן"
    d.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert authz.can(cmd, authz.Action.MILITARY_LICENSE_DECIDE, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_rasan_out_of_scope_cannot_decide_military_license(admin_session):
    d = create_node(admin_session, level="department", name="mdl-d4")
    other = create_node(admin_session, level="department", name="mdl-d4-other")
    cmd = create_soldier(admin_session, personal_number="7600004", role="commander")
    cmd.rank = "רסן"
    d.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert not authz.can(cmd, authz.Action.MILITARY_LICENSE_DECIDE, target_node=other, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
