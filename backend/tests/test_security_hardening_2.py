import pytest


def test_swap_approve_is_dm_global_action():
    from app.auth.authz import Action, _DM_GLOBAL_ACTIONS
    assert Action.SWAP_APPROVE in _DM_GLOBAL_ACTIONS


def test_node_of_assignment_helper_returns_none_for_unassigned_soldier():
    from unittest.mock import MagicMock
    from app.routes.reserves import _node_of_assignment
    session = MagicMock()
    a = MagicMock()
    a.soldier_id = None
    session.get.return_value = None
    assert _node_of_assignment(session, a) is None


def test_hakpaza_scope_helper_raises_for_out_of_scope():
    """_authorize_assignment_scope raises 403 if actor lacks scope for the soldier's node."""
    from fastapi import HTTPException
    from unittest.mock import MagicMock, patch
    import uuid

    session = MagicMock()
    actor = MagicMock()
    actor.role = "commander"

    fake_assignment_id = uuid.uuid4()

    # can() returns False → helper raises 403
    with patch("app.routes.hakpaza.can", return_value=False), \
         patch("app.routes.hakpaza.scope_root_ids", return_value=set()):
        with pytest.raises(HTTPException) as exc_info:
            from app.routes.hakpaza import _authorize_assignment_scope
            _authorize_assignment_scope(session, actor, fake_assignment_id)
        assert exc_info.value.status_code == 403


def test_solver_settings_time_limit_bound():
    from pydantic import ValidationError
    from app.routes.algorithm import SolverSettingsIn

    valid = SolverSettingsIn(time_limit_seconds=60)
    assert valid.time_limit_seconds == 60

    with pytest.raises(ValidationError):
        SolverSettingsIn(time_limit_seconds=9999)

    with pytest.raises(ValidationError):
        SolverSettingsIn(time_limit_seconds=1)
