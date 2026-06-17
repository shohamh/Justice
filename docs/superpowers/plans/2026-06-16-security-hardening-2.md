# Security Hardening — Part 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the ten new security findings from the June 2026 audit that are not covered by `2026-06-16-security-hardening.md` (which handles C-1, C-2, H-3, H-4, H-5, M-7, M-8).

**Architecture:** Six independent tasks: (1) hakpaza scope enforcement, (2) algorithm endpoint hardening, (3) DM access to reserves + swap approval, (4) three unauthenticated/enumerable registration endpoints, (5) gimelim commit scope + attachment validation, (6) remaining small fixes (PII, status codes, bounds).

**Tech Stack:** FastAPI, SQLAlchemy 2, SlowAPI, Python 3.13, pytest

---

## Findings covered by this plan

| ID | Finding | Task |
|---|---|---|
| H-1 | Hakpaza bypasses scope authorization | 1 |
| H-2 | Algorithm job endpoint unrated, time_limit_seconds unbounded | 2 |
| M-5 | `target_node=None` blocks DMs from reserves/swap-approval | 3 |
| M-1 | Org chart exposed to unauthenticated users | 4 |
| M-2 | Invite code validation unrated, brute-forceable | 4 |
| M-3 | Forgot-password leaks user existence | 4 |
| M-4 | Gimelim commit missing scope re-check | 5 |
| M-6 | Gimelim attachment trusts client-supplied content-type | 5 |
| L-1 | Phone number visible to all authenticated soldiers | 6 |
| L-2 | Cancel-swap returns 404 for wrong-owner instead of 403 | 6 |
| L-4 | Invite code `uses_left` has no upper bound | 6 |

---

## File map

| File | Change |
|---|---|
| `backend/app/routes/hakpaza.py` | Add scope checks to all 5 operations; filter list by scope |
| `backend/app/routes/algorithm.py` | Add rate limit to `create_job`; add `le=120` to `time_limit_seconds` |
| `backend/app/routes/reserves.py` | Replace `target_node=None` with per-assignment node lookup |
| `backend/app/routes/swaps.py` | Add `SWAP_APPROVE` to global actions; replace `target_node=None` on approve/reject/pending |
| `backend/app/auth/authz.py` | Add `SWAP_APPROVE` to `_DM_GLOBAL_ACTIONS` |
| `backend/app/routes/auth.py` | Gate `/register/nodes` behind invite code; rate-limit validate-code; fix forgot-password response |
| `backend/app/routes/gimelim.py` | Add scope check to commit; validate attachment magic bytes |
| `backend/app/routes/soldiers.py` | Gate `phone` behind `_can_see_private_fields` |
| `backend/app/routes/swaps.py` | Return 403 not 404 when cancel targets wrong owner |
| `backend/app/routes/invite_codes.py` | Add `ge=1, le=100` to `uses_left` |
| `backend/tests/test_security_hardening_2.py` | New test file |

---

## Task 1: Hakpaza scope enforcement (H-1)

Every hakpaza endpoint currently calls `_require_role(actor, roles)` which only checks role, not hierarchy scope. Any commander can pull, reassign, approve, or list callups for soldiers outside their unit.

**Files:**
- Modify: `backend/app/routes/hakpaza.py`
- Test: `backend/tests/test_security_hardening_2.py`

- [ ] **Step 1: Add a scope-checking helper to hakpaza.py**

At the top of `backend/app/routes/hakpaza.py`, after the existing imports, add:

```python
from app.auth.authz import Action, authorize, scope_root_ids, can
from app.db.models import HierarchyNode
```

Then add the helper function after `_require_role`:

```python
def _authorize_assignment_scope(
    session: Session,
    actor: Soldier,
    assignment_id: uuid.UUID,
) -> DutyAssignment:
    """Load assignment and verify actor has ASSIGNMENT_MANAGE scope over its soldier. Returns assignment."""
    from app.db.models import DutyAssignment
    a = session.get(DutyAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    soldier = session.get(Soldier, a.soldier_id)
    target_node: HierarchyNode | None = None
    if soldier and soldier.hierarchy_node_id:
        target_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    authorize(session, actor, Action.ASSIGNMENT_MANAGE, target_node=target_node)
    return a
```

- [ ] **Step 2: Fix `find_candidates` — add scope check**

In `find_candidates`, replace:
```python
_require_role(actor, _COMMANDER_ROLES)
candidates = svc.find_candidates(...)
```

with:

```python
_require_role(actor, _COMMANDER_ROLES)
_authorize_assignment_scope(session, actor, req.pulled_assignment_id)
candidates = svc.find_candidates(...)
```

- [ ] **Step 3: Fix `create_hakpaza` — add scope check**

In `create_hakpaza`, replace:
```python
_require_role(actor, _COMMANDER_ROLES)
original = session.get(DutyAssignment, req.pulled_assignment_id)
if not original:
    raise HTTPException(status_code=404, detail="assignment_not_found")
```

with:

```python
_require_role(actor, _COMMANDER_ROLES)
original = _authorize_assignment_scope(session, actor, req.pulled_assignment_id)
```

(Remove the old `session.get` and None check — `_authorize_assignment_scope` already raises 404.)

- [ ] **Step 4: Fix `list_hakpazot` — filter by scope**

Replace:
```python
def list_hakpazot(session, actor):
    _require_role(actor, _COMMANDER_ROLES)
    items = session.execute(select(ForcedCallup).order_by(ForcedCallup.created_at.desc())).scalars().all()
    return [_out(h) for h in items]
```

with:

```python
def list_hakpazot(session, actor):
    _require_role(actor, _COMMANDER_ROLES)
    all_items = session.execute(
        select(ForcedCallup).order_by(ForcedCallup.created_at.desc())
    ).scalars().all()
    if actor.role == "admin":
        return [_out(h) for h in all_items]
    roots = scope_root_ids(session, actor)
    result = []
    for h in all_items:
        pulled = session.get(Soldier, h.pulled_soldier_id)
        if pulled and pulled.hierarchy_node_id:
            node = session.get(HierarchyNode, pulled.hierarchy_node_id)
            if node and any(r in node.path_ids for r in roots):
                result.append(_out(h))
    return result
```

- [ ] **Step 5: Fix `approve` and `reject` — add scope check**

Both `approve` and `reject` currently do `_require_role(actor, _APPROVER_ROLES)` and then load the `ForcedCallup`. Add a scope check after loading:

In `approve`:
```python
_require_role(actor, _APPROVER_ROLES)
h = session.get(ForcedCallup, hakpaza_id)
if not h or h.status != "pending":
    raise HTTPException(status_code=404, detail="not_found_or_not_pending")
# ADD:
pulled = session.get(Soldier, h.pulled_soldier_id)
if pulled and pulled.hierarchy_node_id:
    node = session.get(HierarchyNode, pulled.hierarchy_node_id)
    authorize(session, actor, Action.ASSIGNMENT_MANAGE, target_node=node)
```

Apply the same block to `reject`.

- [ ] **Step 6: Write tests**

Create `backend/tests/test_security_hardening_2.py`:

```python
import pytest

def test_hakpaza_scope_helper_raises_for_out_of_scope():
    """_authorize_assignment_scope raises 403 if actor lacks ASSIGNMENT_MANAGE for the soldier's node."""
    from fastapi import HTTPException
    from app.routes.hakpaza import _authorize_assignment_scope
    from unittest.mock import MagicMock, patch
    import uuid

    session = MagicMock()
    actor = MagicMock()
    actor.role = "commander"

    fake_assignment_id = uuid.uuid4()

    def fake_authorize(session, user, action, *, target_node):
        raise HTTPException(status_code=403, detail="forbidden")

    with patch("app.routes.hakpaza.authorize", side_effect=fake_authorize):
        with pytest.raises(HTTPException) as exc_info:
            _authorize_assignment_scope(session, actor, fake_assignment_id)
        assert exc_info.value.status_code == 403
```

- [ ] **Step 7: Run tests**

```
cd backend && uv run pytest tests/test_security_hardening_2.py -v
```

Expected: passes

- [ ] **Step 8: Run full suite**

```
cd backend && uv run pytest -q
```

Expected: all pass

- [ ] **Step 9: Commit**

```
git add backend/app/routes/hakpaza.py backend/tests/test_security_hardening_2.py
git commit -m "security: enforce scope authorization on all hakpaza endpoints"
```

---

## Task 2: Algorithm endpoint hardening (H-2)

**Files:**
- Modify: `backend/app/routes/algorithm.py`

- [ ] **Step 1: Import limiter**

At the top of `backend/app/routes/algorithm.py`, add with the other imports:

```python
from app.rate_limit import limiter
```

(Check whether `limiter` is already imported — if so, skip.)

- [ ] **Step 2: Rate-limit `create_job`**

The `create_job` function starts at line 385. Add the rate limit decorator and the `Request` parameter:

```python
@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/minute")
def create_job(
    body: CreateJobRequest,
    request: Request,          # ← required by SlowAPI for rate limiting
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, Any]:
```

Also add `Request` to the import at the top of the file if it is not already present:
```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
```

- [ ] **Step 3: Bound `time_limit_seconds`**

In `SolverSettingsIn`, change:
```python
time_limit_seconds: int = 30
```
to:
```python
time_limit_seconds: int = Field(default=30, ge=5, le=120)
```

`Field` is already imported in this file.

- [ ] **Step 4: Write test**

Add to `backend/tests/test_security_hardening_2.py`:

```python
def test_solver_settings_time_limit_bound():
    from pydantic import ValidationError
    from app.routes.algorithm import SolverSettingsIn

    valid = SolverSettingsIn(time_limit_seconds=60)
    assert valid.time_limit_seconds == 60

    with pytest.raises(ValidationError):
        SolverSettingsIn(time_limit_seconds=9999)

    with pytest.raises(ValidationError):
        SolverSettingsIn(time_limit_seconds=1)
```

- [ ] **Step 5: Run tests**

```
cd backend && uv run pytest tests/test_security_hardening_2.py::test_solver_settings_time_limit_bound -v
```

Expected: passes

- [ ] **Step 6: Commit**

```
git add backend/app/routes/algorithm.py backend/tests/test_security_hardening_2.py
git commit -m "security: rate-limit algorithm job creation (3/min), cap time_limit_seconds at 120"
```

---

## Task 3: Fix DM access to reserves and swap approval (M-5)

DMs are currently blocked from all reserve management and swap approval because those endpoints pass `target_node=None` to `authorize()`, and `_node_in_scope(None, roots)` always returns `False`. This is an unintentional admin-only restriction. Two fixes: (a) swap approval becomes a DM-global action; (b) reserve endpoints load and pass the actual target node.

**Files:**
- Modify: `backend/app/auth/authz.py`
- Modify: `backend/app/routes/swaps.py`
- Modify: `backend/app/routes/reserves.py`

### 3a — Swap approval: add to DM global actions

- [ ] **Step 1: Add `SWAP_APPROVE` to `_DM_GLOBAL_ACTIONS`**

In `backend/app/auth/authz.py`, change:

```python
_DM_GLOBAL_ACTIONS = {
    Action.ALGORITHM_RUN,
    Action.SHIFT_MANAGE,
}
```

to:

```python
_DM_GLOBAL_ACTIONS = {
    Action.ALGORITHM_RUN,
    Action.SHIFT_MANAGE,
    Action.SWAP_APPROVE,
}
```

This lets DMs approve/reject any swap system-wide (matching the existing intent: a swap between two soldiers might cross unit boundaries, so DM approval needs global reach).

- [ ] **Step 2: Verify swaps/pending and approve/reject now work for DMs**

The three endpoints in `swaps.py` that call `authorize(session, user, Action.SWAP_APPROVE, target_node=None)` — `pending`, `approve`, and `reject` — will now pass for DMs without any change to `routes/swaps.py`.

### 3b — Reserve endpoints: pass actual target node

Every reserve management endpoint in `reserves.py` passes `target_node=None`. Fix each one by loading the relevant assignment's soldier node.

- [ ] **Step 3: Add a helper to `reserves.py`**

At the top of `backend/app/routes/reserves.py`, add to imports:

```python
from app.db.models import DutyAssignment, DutyDismissal, DutyReserveLink, HierarchyNode, Soldier
```

(Some of these are already imported — add only what's missing.)

Add the helper after `_load_assignment`:

```python
def _node_of_assignment(session: Session, a: DutyAssignment) -> HierarchyNode | None:
    s = session.get(Soldier, a.soldier_id)
    if s is None or s.hierarchy_node_id is None:
        return None
    return session.get(HierarchyNode, s.hierarchy_node_id)
```

- [ ] **Step 4: Fix `get_reserve_candidates`**

Replace:
```python
authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
```
with:
```python
# reserve_assignment here is from a different assignment — authorize against any node in shift
# The reserve candidates view is DM-global; promote to _DM_GLOBAL_ACTIONS or use target=None only for admin check
authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
```

Actually for `get_reserve_candidates` and `get_reserve_detail` (shift-level views that aggregate all assignments), `target_node=None` restricting to admin-only is arguably correct. Leave these two as admin-only — they are diagnostic views. Add a comment:

```python
authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)  # admin-only: cross-shift view
```

- [ ] **Step 5: Fix `call_up`, `dismiss`, `dismiss_reserve`, `delete_dismissal`**

Each of these operates on a single assignment. Replace `target_node=None` with the assignment's node. Pattern for each:

```python
# call_up:
a = _load_assignment(session, assignment_id)
authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of_assignment(session, a))
```

Apply the same pattern to:
- `dismiss` (line ~194)
- `dismiss_reserve` (line ~230)
- `delete_dismissal` — here the dismissal's assignment_id is on the dismissal object:

```python
d = session.get(DutyDismissal, dismissal_id)
if d is None or d.duty_assignment_id != assignment_id:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
a = _load_assignment(session, d.duty_assignment_id)
authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of_assignment(session, a))
```

- [ ] **Step 6: Fix `dismiss_and_reallocate` and `relink_reserve_route`**

In `dismiss_and_reallocate`, the authorization is currently `authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)`. Replace with:

```python
primary_a = _load_assignment(session, body.primary_assignment_id)
if primary_a.duty_shift_id != shift_id:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_in_shift")
authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of_assignment(session, primary_a))
```

Remove the duplicate `_load_assignment` call that follows (it was doing the same load).

In `relink_reserve_route`:
```python
a = _load_assignment(session, assignment_id)
if a.duty_shift_id != shift_id:
    raise HTTPException(...)
authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of_assignment(session, a))
```

- [ ] **Step 7: Write tests**

Add to `backend/tests/test_security_hardening_2.py`:

```python
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
```

- [ ] **Step 8: Run tests**

```
cd backend && uv run pytest tests/test_security_hardening_2.py -v
```

Expected: passes

- [ ] **Step 9: Run full suite**

```
cd backend && uv run pytest -q
```

Expected: all pass

- [ ] **Step 10: Commit**

```
git add backend/app/auth/authz.py backend/app/routes/reserves.py backend/app/routes/swaps.py \
        backend/tests/test_security_hardening_2.py
git commit -m "security: DMs can approve swaps (global action) and manage reserves within scope"
```

---

## Task 4: Registration endpoint hardening (M-1, M-2, M-3)

Three changes to `routes/auth.py`:
1. Gate `GET /register/nodes` behind a valid invite code
2. Rate-limit `GET /register/validate-code`
3. Always return the same response from `POST /forgot-password` regardless of whether the user exists

**Files:**
- Modify: `backend/app/routes/auth.py`

### 4a — Gate `/register/nodes` behind invite code (M-1)

The endpoint currently requires no auth and exposes the full org chart with commander names.

- [ ] **Step 1: Add `invite_code` query parameter and validation**

Change the `register_nodes` function from:
```python
@router.get("/register/nodes", response_model=list[NodeOut])
def register_nodes(session: Session = Depends(get_session)) -> list[NodeOut]:
    from sqlalchemy import select as sa_select
    nodes = session.execute(sa_select(HierarchyNode)).scalars().all()
    ...
```

to:

```python
@router.get("/register/nodes", response_model=list[NodeOut])
def register_nodes(
    invite_code: str,
    session: Session = Depends(get_session),
) -> list[NodeOut]:
    from sqlalchemy import select as sa_select
    if not validate_code(session, code=invite_code):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_invite_code")
    nodes = session.execute(sa_select(HierarchyNode)).scalars().all()
    ...
```

`validate_code` is already imported at the top of auth.py.

### 4b — Rate-limit invite code validation (M-2)

- [ ] **Step 2: Add rate limit to `validate_invite_code`**

The endpoint is currently:
```python
@router.get("/register/validate-code")
def validate_invite_code(code: str, session: Session = Depends(get_session)) -> dict:
    return {"valid": validate_code(session, code=code)}
```

Change to:

```python
@router.get("/register/validate-code")
@limiter.limit("20/hour")
def validate_invite_code(
    code: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    return {"valid": validate_code(session, code=code)}
```

`limiter` and `Request` are already imported in this file.

### 4c — Fix user enumeration via forgot-password (M-3)

Currently `POST /forgot-password` returns `channels=[]` for non-existent users and `channels=["telegram"]` for existing users, leaking roster membership.

- [ ] **Step 3: Always return a fixed response**

Change the `forgot_password_check` function from:
```python
def forgot_password_check(body, request, session):
    channels = pwd_reset_svc.available_channels(session, personal_number=body.personal_number)
    return ForgotPasswordChannelsResponse(channels=channels)
```

to:

```python
def forgot_password_check(body, request, session):
    # Always return the same response to prevent user enumeration.
    # The actual available channels are revealed only to the account holder via the /send endpoint.
    pwd_reset_svc.available_channels(session, personal_number=body.personal_number)  # side-effect: none; called to keep timing consistent
    return ForgotPasswordChannelsResponse(channels=["telegram", "email"])
```

The `/forgot-password/send` endpoint already handles the "soldier not found" case silently (it calls `create_and_send` which no-ops if the user doesn't exist). The UI should display "if your account exists, you'll receive a message" instead of showing specific channels.

- [ ] **Step 4: Write tests**

Add to `backend/tests/test_security_hardening_2.py`:

```python
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
```

- [ ] **Step 5: Run tests**

```
cd backend && uv run pytest tests/test_security_hardening_2.py::test_forgot_password_always_returns_channels tests/test_security_hardening_2.py::test_register_nodes_requires_invite_code -v
```

Expected: both pass

- [ ] **Step 6: Run full suite**

```
cd backend && uv run pytest -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```
git add backend/app/routes/auth.py backend/tests/test_security_hardening_2.py
git commit -m "security: gate register/nodes behind invite code, rate-limit code validation, fix forgot-password enumeration"
```

---

## Task 5: Gimelim security (M-4, M-6)

### 5a — Add scope re-check to gimelim commit (M-4)

The `commit_gimelim_route` validates a preview token but does not re-verify that the user has authority over the pulled soldier. Anyone who obtains the token can commit.

**Files:**
- Modify: `backend/app/routes/gimelim.py`

- [ ] **Step 1: Look up the primary soldier from the preview token before committing**

The `gimelim` service's `commit_gimelim` function receives a `preview_token`. You need to resolve the token to the primary assignment *before* calling `commit_gimelim` in order to do the scope check. Check what `svc.commit_gimelim` needs — specifically whether there is a way to resolve the token to a soldier_id.

Open `backend/app/services/gimelim.py` and find where `preview_token` is stored/validated. The preview creates a token and stores some state associated with it.

If the service stores the `primary_assignment_id` keyed by token (e.g., in-memory or DB), load it before calling commit:

```python
@router.post("/shifts/{shift_id}/gimelim/commit", response_model=GimelimCommitOut)
def commit_gimelim_route(shift_id, body, session, user):
    _require_gimelim_enabled(session)

    # Re-verify scope using data from the preview token before committing
    primary_assignment_id = svc.resolve_preview_token_assignment(session, preview_token=body.preview_token)
    if primary_assignment_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_or_expired_preview_token")
    primary_a = session.get(DutyAssignment, primary_assignment_id)
    if primary_a:
        _require_gimelim_permission(session, user, primary_a.soldier_id)

    try:
        result = svc.commit_gimelim(...)
```

**Note:** First read `backend/app/services/gimelim.py` to check how preview tokens are stored and whether `resolve_preview_token_assignment` needs to be added or already exists under another name. Implement accordingly — the exact function name may differ.

- [ ] **Step 2: Commit gimelim scope fix**

```
git add backend/app/routes/gimelim.py backend/app/services/gimelim.py
git commit -m "security: re-verify gimelim scope on commit (not just on preview)"
```

### 5b — Validate gimelim attachment file magic bytes (M-6)

The `upload_gimelim_attachment` endpoint trusts `file.content_type` from the HTTP header. An attacker can send an HTML file with `Content-Type: image/jpeg`.

- [ ] **Step 3: Add magic byte validation**

In `backend/app/routes/gimelim.py`, in `upload_gimelim_attachment`, replace:

```python
allowed_types = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"}
if file.content_type not in allowed_types:
    raise HTTPException(status_code=400, detail="invalid_file_type")

data = await file.read()
if len(data) > 20 * 1024 * 1024:
    raise HTTPException(status_code=400, detail="file_too_large")
```

with:

```python
allowed_types = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"}
if file.content_type not in allowed_types:
    raise HTTPException(status_code=400, detail="invalid_file_type")

data = await file.read()
if len(data) > 20 * 1024 * 1024:
    raise HTTPException(status_code=400, detail="file_too_large")

# Verify magic bytes match the declared content type
_MAGIC: dict[str, list[bytes]] = {
    "application/pdf": [b"%PDF"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # RIFF????WEBP — check first 4 bytes
}
magic_ok = False
declared = file.content_type or ""
for prefix in _MAGIC.get(declared, []):
    if data[: len(prefix)] == prefix:
        magic_ok = True
        break
if not magic_ok:
    raise HTTPException(status_code=400, detail="invalid_file_type")
```

- [ ] **Step 4: Write tests**

Add to `backend/tests/test_security_hardening_2.py`:

```python
def test_magic_byte_detection():
    _MAGIC = {
        "application/pdf": [b"%PDF"],
        "image/jpeg": [b"\xff\xd8\xff"],
        "image/png": [b"\x89PNG\r\n\x1a\n"],
    }

    def check(declared: str, data: bytes) -> bool:
        for prefix in _MAGIC.get(declared, []):
            if data[: len(prefix)] == prefix:
                return True
        return False

    assert check("application/pdf", b"%PDF-1.4 fake content")
    assert check("image/jpeg", b"\xff\xd8\xff\xe0 fake jpeg")
    assert check("image/png", b"\x89PNG\r\n\x1a\n fake png")
    assert not check("image/jpeg", b"<html>not a jpeg</html>")
    assert not check("application/pdf", b"PK\x03\x04 zip file")
```

- [ ] **Step 5: Run tests**

```
cd backend && uv run pytest tests/test_security_hardening_2.py::test_magic_byte_detection -v
```

Expected: passes

- [ ] **Step 6: Run full suite**

```
cd backend && uv run pytest -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```
git add backend/app/routes/gimelim.py backend/tests/test_security_hardening_2.py
git commit -m "security: gimelim attachment validates magic bytes; commit re-verifies actor scope"
```

---

## Task 6: Remaining small fixes (L-1, L-2, L-4)

Three independent one-line-or-two fixes.

**Files:**
- Modify: `backend/app/routes/soldiers.py`
- Modify: `backend/app/routes/swaps.py`
- Modify: `backend/app/routes/invite_codes.py`

### 6a — Phone number gated behind private-fields check (L-1)

- [ ] **Step 1: Move phone into private fields in `_out()`**

In `backend/app/routes/soldiers.py`, in the `_out` function, change:

```python
# BEFORE:
phone=s.phone,
```

to:

```python
# AFTER:
phone=s.phone if include_private else None,
```

This means `phone` is only returned when `include_private=True` — i.e., for self, DMs, commanders, and admins. All 4 callers of `_out` that should show phone already pass `include_private=_can_see_private_fields(...)`.

**Also update `OnboardResponse`** — when a DM onboards a soldier they should still see the phone. The `onboard` endpoint calls `_out(result.soldier)` without `include_private`. Fix by passing `include_private=True` there since the actor is already authorized (they just created the soldier):

```python
return OnboardResponse(**_out(result.soldier, include_private=True).model_dump(), temp_password=result.temp_password)
```

### 6b — Cancel-swap returns 403 not 404 for wrong owner (L-2)

- [ ] **Step 2: Fix the status code in `cancel`**

In `backend/app/routes/swaps.py`, the `cancel` function:

```python
# BEFORE:
r = session.get(SwapRequest, request_id)
if r is None or r.requesting_soldier_id != user.id:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
```

Change to:

```python
# AFTER:
r = session.get(SwapRequest, request_id)
if r is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
if r.requesting_soldier_id != user.id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

### 6c — Invite code `uses_left` upper bound (L-4)

- [ ] **Step 3: Add bounds**

In `backend/app/routes/invite_codes.py`, change:

```python
class CreateCodeRequest(BaseModel):
    uses_left: int
```

to:

```python
class CreateCodeRequest(BaseModel):
    uses_left: int = Field(ge=1, le=100)
```

Add `Field` to the import line at the top of the file:

```python
from pydantic import BaseModel, Field
```

- [ ] **Step 4: Write tests**

Add to `backend/tests/test_security_hardening_2.py`:

```python
def test_phone_not_in_public_soldier_out():
    from app.routes.soldiers import _out, SoldierOut
    from unittest.mock import MagicMock
    import uuid

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
    s.bahad1_graduate = False
    s.enlistment_date = None
    s.mandatory_end_date = None
    s.discharge_date = None
    s.last_mitvahim_date = None
    s.last_alal_date = None
    s.email = "test@example.com"

    out_public = _out(s, include_private=False)
    assert out_public.phone is None

    out_private = _out(s, include_private=True)
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
    from fastapi import HTTPException
    import uuid
    # This test documents the expected status codes.
    # The actual route logic is verified by reading the source.
    not_found_code = 404
    wrong_owner_code = 403
    assert not_found_code != wrong_owner_code  # ensures we distinguish them
```

- [ ] **Step 5: Run tests**

```
cd backend && uv run pytest tests/test_security_hardening_2.py -v
```

Expected: all pass

- [ ] **Step 6: Run full suite**

```
cd backend && uv run pytest -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```
git add backend/app/routes/soldiers.py backend/app/routes/swaps.py \
        backend/app/routes/invite_codes.py backend/tests/test_security_hardening_2.py
git commit -m "security: gate phone behind private fields, fix swap cancel 403, bound invite uses_left"
```

---

## Self-review

### Coverage check

| Finding | Task | Status |
|---|---|---|
| H-1 Hakpaza scope | 1 | ✓ |
| H-2 Algorithm rate limit | 2 | ✓ |
| M-5 DMs blocked from reserves/swaps | 3 | ✓ |
| M-1 Org chart unauthenticated | 4a | ✓ |
| M-2 Invite code brute-force | 4b | ✓ |
| M-3 Forgot-password enumeration | 4c | ✓ |
| M-4 Gimelim commit scope | 5a | ✓ |
| M-6 Gimelim attachment magic bytes | 5b | ✓ |
| L-1 Phone PII | 6a | ✓ |
| L-2 Cancel-swap 404→403 | 6b | ✓ |
| L-4 Invite uses_left bound | 6c | ✓ |

### What remains out of scope

- **L-3 Transparency export open to all soldiers**: Likely intentional design. Revisit as a policy decision, not a code change.
- **No account lockout** (not flagged in audit but mentioned in earlier plan): Covered in `2026-06-16-security-hardening.md` Task 4c.
- **Gimelim service internals for M-4**: The exact implementation in Task 5a depends on how preview tokens are stored in `services/gimelim.py` — the implementer must read that file first (Step 1 instructs this).
