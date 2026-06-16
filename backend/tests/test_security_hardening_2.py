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


def test_forgot_password_always_returns_channels():
    """Response must not differ based on whether the personal number exists."""
    from fastapi.testclient import TestClient
    from app.main import app
    from unittest.mock import patch

    client = TestClient(app)

    with patch("app.services.password_reset.available_channels", return_value=[]):
        resp_missing = client.post("/api/auth/forgot-password", json={"personal_number": "0000000"})

    with patch("app.services.password_reset.available_channels", return_value=["telegram"]):
        resp_existing = client.post("/api/auth/forgot-password", json={"personal_number": "1234567"})

    assert resp_missing.status_code == 200
    assert resp_existing.status_code == 200
    assert resp_missing.json()["channels"] == resp_existing.json()["channels"]
    assert len(resp_missing.json()["channels"]) > 0


def test_register_nodes_requires_invite_code():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get("/api/auth/register/nodes")
    assert resp.status_code == 422  # missing required query param

    resp2 = client.get("/api/auth/register/nodes?invite_code=invalid-code-xyz")
    assert resp2.status_code == 403
