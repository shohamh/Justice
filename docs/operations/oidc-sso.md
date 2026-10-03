# Single sign-on (OIDC) and AD username identity

Justice can sign users in through any OpenID Connect provider (authorization-code flow with PKCE S256). SSO is optional: with no `OIDC_*` settings the feature is disabled, `GET /api/auth/oidc/status` reports `{"enabled": false}`, the login page shows no SSO button and the personal-number/password login is unchanged. Invalid configuration also disables SSO (it never stops the application from starting). No provider, issuer URL or secret is built into the code.

## Provider requirements

- A single trusted issuer. Discovery is read only from `<OIDC_ISSUER>/.well-known/openid-configuration`; the `issuer` in that document must equal `OIDC_ISSUER` exactly (including any trailing slash), and `authorization_endpoint`, `token_endpoint` and `jwks_uri` must be HTTPS.
- The provider must advertise `S256` in `code_challenge_methods_supported`. Plain PKCE is never used.
- ID tokens must be signed with an asymmetric algorithm (RS/PS/ES 256/384/512; the intersection with `id_token_signing_alg_values_supported` is used; `none` and `HS*` are never accepted).
- The ID token must carry `iss`, `sub`, `aud` (containing the client id; `azp` must equal the client id when present or when there are several audiences), `exp`, `iat`, the request `nonce`, and an `email` claim with `email_verified` equal to `true`. A missing or unverified email is refused. Scopes requested: `openid email`.
- Register the redirect URI exactly as configured below. The client may be public (no secret; PKCE only) or confidential (`client_secret_basic`, or `client_secret_post` if that is all the provider supports).

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `OIDC_ISSUER` | empty (disabled) | Issuer URL, HTTPS, no query or fragment |
| `OIDC_CLIENT_ID` | empty | Client id registered at the provider |
| `OIDC_CLIENT_SECRET` | empty | Optional. Empty = public client. Keep it in the secret store, never in git |
| `OIDC_REDIRECT_URI` | empty | Exact callback URL, `https://<host>/api/auth/oidc/callback` |
| `OIDC_TRANSACTION_TTL_SECONDS` | 300 | Lifetime of one login attempt (max 900) |
| `OIDC_REGISTRATION_TTL_SECONDS` | 900 | Lifetime of the registration context for an unmatched identity (max 3600) |
| `OIDC_ALLOW_INSECURE_LOCAL` | false | Allows `http://` for loopback hosts only (local development and the mock provider) |
| `OIDC_RATE_LIMIT` | `20/minute` | Per-client limit for `/auth/oidc/start` and `/auth/oidc/callback` |

The callback always redirects to `FRONTEND_URL` plus a fixed path (`/`, `/register?sso=1` or `/login?sso_error=1`). The reverse proxy must route `/api/` to the backend on the same origin as the frontend so the HttpOnly cookies (`oidc_txn`, `oidc_reg`, `refresh_token`, path-scoped under `/api/auth`) reach it. `COOKIE_SECURE` must stay true outside local development.

## How an identity is matched

1. A subject (`iss` + `sub`) already linked to a soldier logs in as that soldier, whatever email the provider now asserts. Departed soldiers are refused.
2. Otherwise the verified email and the AD username derived from it are matched against soldiers. Exactly one soldier matching both: the subject is linked and the user is signed in. Nothing matching: the user continues to registration without an invite code (email and AD username are read-only, the soldier lands in the holding node and needs the normal enrollment approval). Anything else (one soldier matches only the email, another only the username, several matches, already linked to another subject) is refused with the same generic error and recorded as an identity conflict that an admin resolves on the admin identity conflicts screen.
3. Every failure looks identical to the user (`/login?sso_error=1`); the reason is only in the audit log (`auth.sso.login.failure`, reason code, no claims).

HR sync conflicts (duplicate personal numbers in the feed, HR emails or usernames colliding with another soldier) are warned about and resolved on the HR sync review page; they never fail the sync.

## AD username assumptions (provider-specific, selected application policy)

The AD username is the local part of the email, interpreted as a legacy Windows `sAMAccountName`:

- lowercase (the email is lowercased and trimmed; emails are stored canonically and are unique case-insensitively);
- at most 20 characters;
- must not contain any of `" / \ [ ] : ; | = , + * ? < >`; nothing is stripped or replaced, an offending address is rejected rather than rewritten;
- dots are kept (`dana.levi` stays `dana.levi`), and `+` is rejected rather than treated as a plus-tag;
- only ASCII dot-atom local parts and ASCII hostnames are accepted; quoted local parts and Unicode are rejected.

If your directory uses a different convention (longer usernames, aliases, UPN prefixes), change `app/services/identity.py` before enabling SSO; this is a Justice policy, not something the provider guarantees. The directory must also make sure the provider's `email` claim is the mailbox the soldier owns and is marked verified.

## Rollout notes

- The identity migrations (`20261002_soldier_identity` through `20261003_merge_identity_heads`) refuse to run while existing soldiers have conflicting, malformed or untrimmed emails or personal numbers. Run `python -m app.scripts.identity_preflight` first (exit code 1 lists soldier ids, never addresses), fix the data, then `alembic upgrade head`.
- The head revision is a merge, so step back with an explicit revision (`alembic downgrade 4858092e72e7` reverts the whole identity chain) rather than `downgrade -1`, which Alembic reports as an ambiguous walk.
- The one-time authorization code and state appear in the callback URL. The application redacts them from its own error logs and from the uvicorn access log; if a reverse proxy or load balancer in front of Justice writes access logs, strip the query string of `/api/auth/oidc/callback` there too.

## Local mock provider

`backend/tests/support/mock_oidc.py` is an in-process provider with throwaway RSA keys and synthetic `example.test` data. It validates PKCE, the exact redirect URI, client authentication and one-time codes.

Unit and integration tests use it through `httpx.MockTransport` (`MockOidcProvider().transport()`); no setup is needed.

For browser runs, serve it on loopback and point a local backend at it (all values below are local, throwaway placeholders). Terminal 1 runs the mock provider; the host and port must match the issuer:

```powershell
cd backend
.\.venv\Scripts\python -c "import uvicorn; from tests.support.mock_oidc import MockOidcProvider; p = MockOidcProvider(issuer='http://127.0.0.1:9100', redirect_uri='http://localhost:8000/api/auth/oidc/callback'); uvicorn.run(p.asgi_app(), host='127.0.0.1', port=9100)"
```

Terminal 2 runs the backend with SSO enabled against it (the mock's client secret is a fixed placeholder defined in `mock_oidc.py`; read it from there for `OIDC_CLIENT_SECRET`, or construct the provider with `client_secret=''` and leave the variable unset to test a public client):

```powershell
$env:OIDC_ISSUER = 'http://127.0.0.1:9100'
$env:OIDC_CLIENT_ID = 'justice-test-client'
$env:OIDC_REDIRECT_URI = 'http://localhost:8000/api/auth/oidc/callback'
$env:OIDC_ALLOW_INSECURE_LOCAL = 'true'
$env:COOKIE_SECURE = 'false'
.\dev.ps1
```

The mock picks who the next login is from `POST <mock>/__identity` with `{"subject": "...", "email": "someone@example.test", "email_verified": true}`. The Playwright spec `frontend/tests/e2e/oidc_sso.spec.ts` is skipped unless `E2E_OIDC_MOCK_URL` is set to the mock's base URL (and `E2E_OIDC_DISABLED=1` against a backend with no `OIDC_*` settings for the unconfigured case).

## Real-provider browser tests (Keycloak)

`frontend/tests/e2e/oidc/` runs the SSO journeys in a real browser against a real OIDC provider (Keycloak 26, `start-dev`, imported from the checked-in test realm `justice-test-realm.json`: a confidential client with the exact redirect URI and PKCE S256 enforced, and synthetic `example.test` users sharing one throwaway test password). Everything in that folder is a local test fixture; never reuse its client secret, password or realm outside local testing.

```powershell
cd frontend
$env:E2E_BROWSER_CHANNEL = ''          # use Playwright's bundled Chromium instead of the system Chrome
.\tests\e2e\oidc\run.ps1               # start, test, tear down (add -KeepUp to leave it running, -Down to clean up)
.\tests\e2e\oidc\run.ps1 -PlaywrightArgs '-g','ambiguous'
```

`run.ps1` starts the throwaway containers `oidc-e2e-pg`, `oidc-e2e-redis` and `oidc-e2e-keycloak` (memory capped: about 200 MB, 64 MB and 900 MB with a 512 MB Java heap) on ports 55440, 56392 and 8411, migrates and seeds a fresh database, seeds two e-mail identities (`seed_identities.py`), runs the backend on :8410 and Vite on :5183 natively with `OIDC_*` pointing at Keycloak, runs `playwright.oidc.config.ts`, then stops and removes everything it started. It does not touch the normal dev stack ports, and Docker Compose is not used.

The issuer is `http://127.0.0.1:8411/realms/justice-test` while the app is at `http://localhost:5183`. They are different sites, so the cross-site callback redirect and the `oidc_txn` (Lax) and `oidc_reg` / `refresh_token` (Strict) cookie behaviour are exercised for real. A `*.localhost` issuer host is not used: Python on Windows cannot resolve it and the backend only accepts literal loopback hosts over http.

Keycloak users and what they exercise: `sso.existing` (matches seeded soldier 1000003), `sso.new1` (unmatched, registers without an invite code), `sso.ambig` (same AD username as seeded soldier 1000004 but another e-mail domain: a username-only match, which is the only ambiguity the database constraints allow), `sso.unverified` (`emailVerified=false`). The first Keycloak login after a cold start can take a minute on a small machine.
