import pytest


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
