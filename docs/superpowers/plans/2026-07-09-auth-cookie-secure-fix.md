# Auth Cookie Secure-Flag Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop soldiers from being silently logged out on page refresh due to a misconfigured `COOKIE_SECURE` setting, and make future misconfiguration loud instead of silent.

**Architecture:** `backend/app/settings.py:24` defaults `cookie_secure` to `True`, which makes browsers refuse to store/send the `refresh_token` cookie over plain HTTP. The repo's own `.env` already overrides this to `false` locally, but `.env.example` — the template every fresh setup copies — never sets it, so a new environment served over HTTP inherits the `True` default and hits exactly this bug. Fix the template default, and add a runtime warning so a `secure=true` cookie being set on a plain-HTTP request is visible in logs instead of manifesting as an unexplained logout.

**Tech Stack:** FastAPI, Python `logging` (backend). No frontend changes required — this is a backend configuration/observability fix.

## Global Constraints

- Do not weaken `cookie_secure` for real HTTPS deployments — the fix is about defaults and diagnosability, not disabling the secure flag globally.

---

### Task 1: Fix the `.env.example` default and warn on mismatch

**Files:**
- Modify: `.env.example`
- Modify: `backend/app/routes/auth.py`
- Test: `backend/tests/integration/test_login.py`

**Interfaces:**
- Produces: a `logging.getLogger("app.auth")` warning emitted whenever a cookie is set with `secure=True` on a request whose scheme is not `https`.

- [ ] **Step 1: Write the failing test**

First check the existing structure of `backend/tests/integration/test_login.py` (`grep -n "^def test_\|^import\|^from" backend/tests/integration/test_login.py`) so the new test matches its fixtures/imports. Append:

```python
import logging


def test_warns_when_secure_cookie_set_over_plain_http(client, admin_session, caplog, monkeypatch):
    from app.settings import get_settings
    from tests.helpers import create_soldier

    get_settings.cache_clear()
    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    try:
        s = create_soldier(admin_session, personal_number="7700001", password="password-1234")
        with caplog.at_level(logging.WARNING, logger="app.auth"):
            r = client.post(
                "/api/auth/login",
                json={"personal_number": "7700001", "password": "password-1234"},
                headers={"X-Forwarded-Proto": "http"},
            )
        assert r.status_code == 200
        assert any("cookie_secure" in rec.message.lower() for rec in caplog.records)
    finally:
        monkeypatch.delenv("COOKIE_SECURE", raising=False)
        get_settings.cache_clear()
```

Run: `cd backend && grep -n "def client\|TestClient(" tests/conftest.py` first to confirm how the `client` fixture is built (specifically whether it sets a base `scheme`/host that would already read as `https`) — if the `TestClient` fixture always reports `https` scheme by default (Starlette's `TestClient` defaults its base_url to `http://testserver` unless overridden), no adjustment is needed; the header above is included defensively but the check in Step 3 should key off `request.url.scheme`, which for the default `TestClient` base URL is `http`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_login.py -k warns_when_secure -v`
Expected: FAIL — no warning logged (the code doesn't check/warn yet).

- [ ] **Step 3: Implement the warning**

In `backend/app/routes/auth.py`, add near the top (alongside the other imports):

```python
import logging

_logger = logging.getLogger("app.auth")
```

Add a small helper right after `_client_context`:

```python
def _warn_if_insecure_cookie_mismatch(request: Request, settings) -> None:
    if settings.cookie_secure and request.url.scheme != "https":
        _logger.warning(
            "cookie_secure is enabled but this request arrived over %s — the "
            "refresh_token cookie will be silently dropped by the browser. "
            "Set COOKIE_SECURE=false for non-HTTPS environments.",
            request.url.scheme,
        )
```

Call it at the top of `login()` (right after `settings = get_settings()`) and at the top of `refresh()` (right after `settings = get_settings()`... note `refresh()` currently calls `get_settings()` twice, once implicitly via `get_settings().cookie_secure` at line 222 and once via the local `settings` variable at line 214 — use the existing `settings` local in both places):

```python
    _warn_if_insecure_cookie_mismatch(request, settings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_login.py -k warns_when_secure -v`
Expected: passed

- [ ] **Step 5: Fix the `.env.example` default**

In `.env.example`, add a line after `LOGIN_RATE_LIMIT=5/5minutes`:

```
COOKIE_SECURE=false
```

Add a one-line comment above it explaining why:

```
# Set to true only when served over real HTTPS — browsers silently drop the
# refresh cookie over plain HTTP if this is true, causing logout-on-refresh.
COOKIE_SECURE=false
```

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && pytest -q`
Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add .env.example backend/app/routes/auth.py backend/tests/integration/test_login.py
git commit -m "fix: default COOKIE_SECURE=false in env template and warn on http/secure-cookie mismatch"
```

---

### Task 2: Verify the Tailscale funnel deployment path

**Files:**
- None (verification-only task; update `.env` on the deployed host if it's found misconfigured, and update `README.md` if setup instructions are unclear).

- [ ] **Step 1: Check the current deployed/funnel host's `.env`**

Per [feedback_tailscale_funnel.md] (existing project memory), external/phone access goes through `tailscale funnel`. Confirm the funnel terminates HTTPS at the Tailscale layer and proxies to the app over `http://localhost:5173` / `:8000` internally — if so, the backend itself still sees plain HTTP requests, so `COOKIE_SECURE` must be `false` on that host too (Tailscale's HTTPS termination doesn't make the backend's own view of the request secure). Check the deployed host's `.env` for `COOKIE_SECURE` and set it to `false` if missing or `true`, restarting the backend to pick up the change.

- [ ] **Step 2: Manually verify**

Log in via the Tailscale funnel URL on a phone/external browser, refresh the page, and confirm the session survives (no forced re-login). Also verify on local dev (`http://localhost:5173`) that the warning added in Task 1 does **not** fire (since local `.env` already has `COOKIE_SECURE=false`).

- [ ] **Step 3: Note in README if setup steps need clarifying**

If `README.md` documents `.env` setup and doesn't already mention `COOKIE_SECURE`, add a line under wherever `ALLOWED_ORIGINS`/similar env vars are documented, explaining it must stay `false` unless the app is served over real HTTPS. Check first with `grep -n "COOKIE_SECURE\|ALLOWED_ORIGINS" README.md`.

- [ ] **Step 4: Commit (if README changed)**

```bash
git add README.md
git commit -m "docs: clarify COOKIE_SECURE must be false for non-HTTPS deployments"
```
