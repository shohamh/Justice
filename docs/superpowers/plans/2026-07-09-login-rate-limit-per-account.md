# Login Rate Limit — Add Per-Account Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the existing IP-based login rate limit, and add a second, independent rate limit keyed on the submitted `personal_number`, so soldiers sharing an IP (e.g. a base's shared internet) no longer throttle each other's own accounts, while an attacker also can't dodge the per-account limit by rotating IPs.

**Architecture:** slowapi supports stacking multiple `@limiter.limit(...)` decorators on one route — both get evaluated together on every request. Add a second decorator on `POST /auth/login` with a custom `key_func` that extracts `personal_number` from the already-parsed request body (cached on `request._body` by the time slowapi's key func runs, since FastAPI resolves the body dependency before calling the decorated function) and falls back to the client IP if the body can't be read. Give it its own settings value so it's independently tunable from the existing IP limit.

**Tech Stack:** FastAPI, slowapi, pytest (backend).

## Global Constraints

- The existing per-soldier DB lockout (`Soldier.failed_login_count`/`locked_until`, `backend/app/routes/auth.py:136-149`) is correct as-is and out of scope — this plan only touches the request-rate-limiting layer in front of it.
- Both limits must pass for a login attempt to proceed (i.e. exceeding *either* returns 429) — this is slowapi's default behavior when multiple limits are registered on one route, no extra code needed for that part.

---

### Task 1: Add the per-account rate limit

**Files:**
- Modify: `backend/app/settings.py`
- Modify: `backend/app/routes/auth.py`
- Modify: `.env.example`
- Test: `backend/tests/integration/test_login_rate_limit.py` (new)

**Interfaces:**
- Produces: `Settings.login_account_rate_limit: str` (new field, alias `LOGIN_ACCOUNT_RATE_LIMIT`, default `"10/5minutes"`); `_login_account_key(request: Request) -> str` in `backend/app/routes/auth.py`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_login_rate_limit.py`:

```python
from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.requests import Request

from tests.helpers import create_soldier


def test_login_account_key_extracts_personal_number():
    from app.routes.auth import _login_account_key

    scope = {"type": "http", "client": ("1.2.3.4", 1234), "headers": []}
    request = Request(scope)
    request._body = json.dumps({"personal_number": "1234567", "password": "x"}).encode()

    assert _login_account_key(request) == "login-account:1234567"


def test_login_account_key_falls_back_to_ip_on_bad_body():
    from app.routes.auth import _login_account_key

    scope = {"type": "http", "client": ("1.2.3.4", 1234), "headers": []}
    request = Request(scope)
    request._body = b"not json"

    assert _login_account_key(request) == "1.2.3.4"


def test_repeated_failed_logins_for_one_account_get_rate_limited(
    client: TestClient, admin_session: Session, monkeypatch
):
    from app.settings import get_settings
    from app.rate_limit import limiter

    monkeypatch.setenv("LOGIN_ACCOUNT_RATE_LIMIT", "2/minute")
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "1000/minute")
    get_settings.cache_clear()
    limiter.reset()
    try:
        create_soldier(admin_session, personal_number="7900001", password="password-1234")

        for _ in range(2):
            r = client.post(
                "/api/auth/login",
                json={"personal_number": "7900001", "password": "wrong"},
            )
            assert r.status_code == 401

        r = client.post(
            "/api/auth/login",
            json={"personal_number": "7900001", "password": "wrong"},
        )
        assert r.status_code == 429
    finally:
        get_settings.cache_clear()
        limiter.reset()


def test_rate_limit_on_one_account_does_not_block_another(
    client: TestClient, admin_session: Session, monkeypatch
):
    from app.settings import get_settings
    from app.rate_limit import limiter

    monkeypatch.setenv("LOGIN_ACCOUNT_RATE_LIMIT", "1/minute")
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "1000/minute")
    get_settings.cache_clear()
    limiter.reset()
    try:
        create_soldier(admin_session, personal_number="7900002", password="password-1234")
        create_soldier(admin_session, personal_number="7900003", password="password-1234")

        r1 = client.post("/api/auth/login", json={"personal_number": "7900002", "password": "wrong"})
        assert r1.status_code == 401
        r2 = client.post("/api/auth/login", json={"personal_number": "7900002", "password": "wrong"})
        assert r2.status_code == 429

        # A different account, same client/IP, is unaffected.
        r3 = client.post("/api/auth/login", json={"personal_number": "7900003", "password": "wrong"})
        assert r3.status_code == 401
    finally:
        get_settings.cache_clear()
        limiter.reset()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_login_rate_limit.py -v`
Expected: FAIL — `ImportError: cannot import name '_login_account_key'`, and `LOGIN_ACCOUNT_RATE_LIMIT` isn't a recognized field yet (the two `monkeypatch.setenv` calls won't error, but the limit won't actually change anything since it doesn't exist, so the rate-limit assertions will also fail — 429 never happens because only the fixed-at-import-time IP limit is active).

- [ ] **Step 3: Add the setting**

In `backend/app/settings.py`, add right after `login_rate_limit`:

```python
    login_account_rate_limit: str = Field(default="10/5minutes", alias="LOGIN_ACCOUNT_RATE_LIMIT")
```

- [ ] **Step 4: Make the login route re-read settings per-request and add the second limit**

In `backend/app/routes/auth.py`, the current decorator evaluates `get_settings().login_rate_limit` once at import time (`@limiter.limit(get_settings().login_rate_limit)`), which also blocks clean testing via env var overrides. slowapi's `limit_value` parameter accepts a callable, evaluated per-request — switch both limits to callables so they pick up `monkeypatch.setenv` + `get_settings.cache_clear()` in tests (and any future runtime config change) immediately:

```python
def _login_account_key(request: Request) -> str:
    """Rate-limit key for /auth/login: the submitted personal_number, falling
    back to client IP if the body is missing/malformed."""
    try:
        raw = getattr(request, "_body", b"") or b""
        data = json.loads(raw)
        pn = data.get("personal_number")
        if pn:
            return f"login-account:{pn}"
    except Exception:
        pass
    return get_remote_address(request)
```

Add the imports this needs at the top of `backend/app/routes/auth.py`:

```python
import json

from slowapi.util import get_remote_address
```

Change the decorator stack on `login()` (currently lines 104-105) from:

```python
@router.post("/login", response_model=LoginResponse)
@limiter.limit(get_settings().login_rate_limit)
def login(
```

to:

```python
@router.post("/login", response_model=LoginResponse)
@limiter.limit(lambda: get_settings().login_rate_limit)
@limiter.limit(lambda: get_settings().login_account_rate_limit, key_func=_login_account_key)
def login(
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_login_rate_limit.py -v`
Expected: all passed

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && pytest -q`
Expected: no regressions — specifically re-check `backend/tests/test_security_hardening.py::test_login_rate_limit_default_is_10_per_5_minutes`, which should still pass unchanged since `login_rate_limit`'s default didn't change.

- [ ] **Step 7: Document the new env var**

In `.env.example`, add right after `LOGIN_RATE_LIMIT=5/5minutes`:

```
LOGIN_ACCOUNT_RATE_LIMIT=5/5minutes
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/settings.py backend/app/routes/auth.py backend/tests/integration/test_login_rate_limit.py .env.example
git commit -m "feat: add per-account login rate limit alongside the existing per-IP limit"
```
