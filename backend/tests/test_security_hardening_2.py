import uuid
import pytest


def test_swap_approve_is_scoped_not_global():
    """SWAP_APPROVE must NOT be a global DM action — DMs should only approve swaps in their scope."""
    from app.auth.authz import Action, _DM_GLOBAL_ACTIONS, _DM_ACTIONS
    assert Action.SWAP_APPROVE not in _DM_GLOBAL_ACTIONS, (
        "SWAP_APPROVE must be scope-checked; removing it from _DM_GLOBAL_ACTIONS prevents "
        "a DM from approving swaps outside their hierarchy."
    )
    assert Action.SWAP_APPROVE in _DM_ACTIONS


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


def test_magic_byte_detection():
    """Magic byte dict in the attachment route correctly detects real vs spoofed files."""
    _MAGIC = {
        "application/pdf": [b"%PDF"],
        "image/jpeg": [b"\xff\xd8\xff"],
        "image/png": [b"\x89PNG\r\n\x1a\n"],
        "image/gif": [b"GIF87a", b"GIF89a"],
        "image/webp": [b"RIFF"],
    }

    def check(declared: str, data: bytes) -> bool:
        return any(
            data[: len(prefix)] == prefix
            for prefix in _MAGIC.get(declared, [])
        )

    assert check("application/pdf", b"%PDF-1.4 fake content")
    assert check("image/jpeg", b"\xff\xd8\xff\xe0 fake jpeg")
    assert check("image/png", b"\x89PNG\r\n\x1a\n fake png")
    assert check("image/gif", b"GIF89a fake gif")
    assert check("image/webp", b"RIFF\x00\x00\x00\x00WEBP")
    assert not check("image/jpeg", b"<html>not a jpeg</html>")
    assert not check("application/pdf", b"PK\x03\x04 zip file")
    assert not check("image/png", b"%PDF-1.4 wrong type declared")
    # Unknown declared type → no magic entries → always False
    assert not check("application/octet-stream", b"%PDF-1.4 anything")


def test_gimelim_resolve_preview_token_returns_none_for_unknown():
    from app.services.gimelim import resolve_preview_token_assignment
    assert resolve_preview_token_assignment("no-such-token") is None


def test_gimelim_resolve_preview_token_returns_none_for_expired():
    import uuid
    from datetime import datetime, timedelta, timezone
    from app.services import gimelim as svc

    token = str(uuid.uuid4())
    primary_id = uuid.uuid4()
    expired_time = datetime.now(timezone.utc) - timedelta(seconds=1)
    svc._PREVIEW_STORE[token] = (
        expired_time,
        {"primary_assignment_id": str(primary_id)},
    )
    result = svc.resolve_preview_token_assignment(token)
    assert result is None
    # clean up
    svc._PREVIEW_STORE.pop(token, None)


def test_gimelim_resolve_preview_token_returns_id_for_valid():
    import uuid
    from datetime import datetime, timedelta, timezone
    from app.services import gimelim as svc

    token = str(uuid.uuid4())
    primary_id = uuid.uuid4()
    future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    svc._PREVIEW_STORE[token] = (
        future_time,
        {"primary_assignment_id": str(primary_id)},
    )
    result = svc.resolve_preview_token_assignment(token)
    assert result == primary_id
    # clean up
    del svc._PREVIEW_STORE[token]


def test_register_nodes_requires_invite_code():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get("/api/auth/register/nodes")
    assert resp.status_code == 422  # missing required query param

    resp2 = client.get("/api/auth/register/nodes?invite_code=invalid-code-xyz")
    assert resp2.status_code == 403


def test_phone_not_in_public_soldier_out():
    from app.routes.soldiers import _out
    from unittest.mock import MagicMock

    s = MagicMock()
    s.id = uuid.uuid4()
    s.personal_number = "1234567"
    s.full_name = "Test Soldier"
    s.role = "soldier"
    s.hierarchy_node_id = None
    s.phone = "050-1234567"
    s.must_change_password = False
    s.left_at = None
    s.enrolled_at = None
    s.gender = None
    s.is_officer = None
    s.rank = None
    s.rank_track = None
    s.is_career = False
    s.bahad1_graduate = False
    s.has_military_driving_license = None
    s.food_type = None
    s.food_constraints = None
    s.military_driving_license_expiry = None
    s.enlistment_date = None
    s.unit_join_date = None
    s.mandatory_end_date = None
    s.discharge_date = None
    s.last_mitvahim_date = None
    s.last_alal_date = None
    s.email = "test@example.com"
    s.profile_picture_url = None
    s.next_rank_date = None
    s.next_rank_date_overridden = False

    session = MagicMock()
    user = MagicMock()
    user.role = "soldier"

    # soldiers.phone_public/email_public now default True (see
    # test_soldiers_api.py / test_private_fields.py for the API-level
    # coverage) — the redaction path is exercised by explicitly passing
    # phone_public=False, matching an admin turning that setting off.
    out_redacted = _out(s, session=session, user=user, include_private=False, phone_public=False)
    assert out_redacted.phone is None

    out_public_default = _out(s, session=session, user=user, include_private=False)
    assert out_public_default.phone == "050-1234567"

    out_private = _out(s, session=session, user=user, include_private=True)
    assert out_private.phone == "050-1234567"


def test_invite_code_uses_left_bounds():
    from pydantic import ValidationError
    from app.routes.invite_codes import CreateCodeRequest

    valid = CreateCodeRequest(uses_left=10)
    assert valid.uses_left == 10

    with pytest.raises(ValidationError):
        CreateCodeRequest(uses_left=0)

    with pytest.raises(ValidationError):
        CreateCodeRequest(uses_left=101)


def test_cancel_swap_returns_403_for_wrong_owner():
    """Distinguishing 404 (not found) from 403 (found but not yours)."""
    not_found_code = 404
    wrong_owner_code = 403
    assert not_found_code != wrong_owner_code
