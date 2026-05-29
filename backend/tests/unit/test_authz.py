from app.auth import authz
from tests.helpers import create_node, create_soldier


def _roots(session, user):
    return authz.scope_root_ids(session, user)


def test_admin_can_everything_globally(admin_session):
    admin = create_soldier(admin_session, personal_number="7000001", role="admin")
    d = create_node(admin_session, level="department", name="d")
    assert authz.can(
        admin, authz.Action.SOLDIER_CREATE, target_node=d, roots=_roots(admin_session, admin)
    )
    assert authz.can(
        admin, authz.Action.HIERARCHY_MANAGE, target_node=d, roots=_roots(admin_session, admin)
    )
    assert authz.can(
        admin, authz.Action.SOLDIER_ASSIGN_ROLE, target_node=d, roots=_roots(admin_session, admin)
    )


def test_duty_manager_scoped_to_own_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    dm = create_soldier(
        admin_session, personal_number="7000002", role="duty_manager", hierarchy_node_id=b.id
    )
    roots = _roots(admin_session, dm)
    assert authz.can(dm, authz.Action.SOLDIER_CREATE, target_node=b, roots=roots)
    assert not authz.can(dm, authz.Action.SOLDIER_CREATE, target_node=other, roots=roots)
    assert not authz.can(dm, authz.Action.SOLDIER_ASSIGN_ROLE, target_node=b, roots=roots)


def test_commander_read_only_in_commanded_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7000003", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    assert authz.can(cmd, authz.Action.SOLDIER_READ, target_node=b, roots=roots)
    assert authz.can(cmd, authz.Action.HIERARCHY_READ, target_node=b, roots=roots)
    assert not authz.can(cmd, authz.Action.SOLDIER_CREATE, target_node=b, roots=roots)


def test_plain_soldier_has_no_management(admin_session):
    d = create_node(admin_session, level="department", name="d")
    s = create_soldier(
        admin_session, personal_number="7000004", role="soldier", hierarchy_node_id=d.id
    )
    roots = _roots(admin_session, s)
    assert roots == set()
    assert not authz.can(s, authz.Action.SOLDIER_READ, target_node=d, roots=roots)


def test_commander_can_grant_and_read_exemptions_in_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    cmd = create_soldier(admin_session, personal_number="7100001", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    assert authz.can(cmd, authz.Action.EXEMPTION_GRANT, target_node=b, roots=roots)
    assert authz.can(cmd, authz.Action.EXEMPTION_READ, target_node=b, roots=roots)
    assert not authz.can(cmd, authz.Action.EXEMPTION_GRANT, target_node=other, roots=roots)


def test_duty_manager_can_grant_exemptions_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    dm = create_soldier(
        admin_session, personal_number="7100002", role="duty_manager", hierarchy_node_id=b.id
    )
    roots = _roots(admin_session, dm)
    assert authz.can(dm, authz.Action.EXEMPTION_GRANT, target_node=b, roots=roots)


def test_plain_soldier_cannot_grant_exemptions(admin_session):
    d = create_node(admin_session, level="department", name="d")
    s = create_soldier(
        admin_session, personal_number="7100003", role="soldier", hierarchy_node_id=d.id
    )
    roots = _roots(admin_session, s)
    assert not authz.can(s, authz.Action.EXEMPTION_GRANT, target_node=d, roots=roots)


def test_duty_manager_can_manage_assignments_and_scores_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="d-s4")
    b = create_node(admin_session, level="branch", name="b-s4", parent=d)
    other = create_node(admin_session, level="department", name="other-s4")
    dm = create_soldier(
        admin_session, personal_number="7400001", role="duty_manager", hierarchy_node_id=b.id
    )
    roots = _roots(admin_session, dm)
    assert authz.can(dm, authz.Action.ASSIGNMENT_MANAGE, target_node=b, roots=roots)
    assert authz.can(dm, authz.Action.SCORE_ADJUST, target_node=b, roots=roots)
    assert not authz.can(dm, authz.Action.ASSIGNMENT_MANAGE, target_node=other, roots=roots)


def test_commander_cannot_manage_assignments(admin_session):
    d = create_node(admin_session, level="department", name="d-s4b")
    b = create_node(admin_session, level="branch", name="b-s4b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7400002", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    assert not authz.can(cmd, authz.Action.ASSIGNMENT_MANAGE, target_node=b, roots=roots)
    assert not authz.can(cmd, authz.Action.SCORE_ADJUST, target_node=b, roots=roots)


def test_plain_soldier_cannot_manage_assignments(admin_session):
    d = create_node(admin_session, level="department", name="d-s4c")
    s = create_soldier(
        admin_session, personal_number="7400003", role="soldier", hierarchy_node_id=d.id
    )
    roots = _roots(admin_session, s)
    assert not authz.can(s, authz.Action.ASSIGNMENT_MANAGE, target_node=d, roots=roots)
