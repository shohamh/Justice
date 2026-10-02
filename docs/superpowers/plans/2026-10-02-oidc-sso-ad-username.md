# OIDC SSO and AD Username Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional provider-configured OIDC sign-in, enforce unique normalized soldier email and email-derived AD username, cross-check every SSO and HR-sync identity against existing soldiers (personal number, email, AD username) so ambiguity is surfaced as an admin-visible conflict instead of guessed, and continue unmatched verified identities into registration without an activation code.

**Architecture:** Keep OIDC protocol handling in a small backend service using a maintained client library, with server-side one-time state/nonce/PKCE transactions. Persist stable issuer/subject links separately from Soldier and issue existing Justice JWT/cookie sessions only after a valid match or completed registration. Centralize email and AD username normalization and one identity-resolution service (exactly-one-match or conflict) so registration, HR sync, imports, admin changes, and self-service updates share the same invariant.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Alembic, maintained Python OIDC client, React/TypeScript, pytest, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-02-oidc-sso-ad-username-design.md`

## Global Constraints

- Email is trimmed and compared case-insensitively; `NULL` is allowed, blank becomes `NULL`; unique email applies to verified and unverified values.
- `ad_username` is derived from the normalized email local part in lowercase, without stripping plus tags or dots; both email and AD username are database-unique when non-null.
- Personal number, normalized email, and derived AD username are each database-unique (`soldiers.personal_number` already is; add a trimmed/non-blank CHECK and include it in migration preflight). The DB is the last line of defence; application code also checks first so conflicts become typed errors, not raw `IntegrityError`s.
- Identity resolution is a single shared function: given a verified email and derived AD username it returns exactly one of `Match(soldier)`, `NoMatch`, or `Ambiguous(candidates)`. A Soldier is a match only when its email and AD username both equal the claim. Zero candidates -> `NoMatch`; more than one candidate, or one soldier matching on email and a *different* one on AD username -> `Ambiguous`. Ambiguity never logs anyone in, never creates a Soldier, and is recorded as an admin-visible `IdentityConflict`.
- HR sync never overrides silently: a personal number that appears more than once in the HR feed, or an HR person whose email/AD username collides with a different Soldier, raises a typed `HrIdentityConflictError` (a `ValueError` subclass) that the sync catches and records as an admin-visible HR sync conflict (warning) listing every candidate. For a duplicated personal number the sync then continues by default with the **latest** record (the last occurrence in the feed; HR records carry no per-record timestamp), and the admin can pick a different candidate as the remembered choice for all future syncs (see Task 8). A collision with a different Soldier's email/AD username is never applied (the DB would reject it): the person's other fields sync and the colliding value is left unchanged.
- Migration reports collisions and does not merge, rename, or arbitrarily select a Soldier.
- Stable identity is `(configured issuer, validated subject)`, never email or `preferred_username`.
- Use Authorization Code + PKCE S256 with transaction-specific state/nonce, exact redirect URI, verified issuer metadata, bounded expiry, and single-use browser-bound transaction.
- Require a verified email claim; no account is created until registration succeeds. Registration reached from an unmatched SSO identity does **not** require an activation/invite code (the verified, unconsumed server-side OIDC context replaces it); personal number, profile fields, and the password field are still required, and ordinary non-SSO registration still requires the invite code. The new soldier lands in the holding node through the existing registration path and stays there, with no elevated access, until a commander at or above mador approves them via the existing enrollment approval flow.
- Keep tokens and PII out of URLs, browser storage, logs, and test artifacts; retain current password login and authorization roles.
- OIDC remains disabled when configuration is absent or invalid; no production issuer or secret is selected in this slice.

## Review Focus

- Duplicate emails differ only in case or surrounding spaces; test migration preflight and DB uniqueness for verified and unverified rows.
- Emails with missing local part, unsupported AD characters, plus tags, dots, or Unicode; test explicitly selected validation policy without silent lossy normalization.
- Callback state, nonce, PKCE verifier, browser cookie, issuer, audience/azp, expiry, signature, or redirect URI mismatches; test each rejects before session issuance.
- Concurrent first-link or registration attempts for one subject, email, or derived username; test PostgreSQL uniqueness and one-time context consumption.
- Expired/disabled Soldier, already-linked subject, changed email, provider outage/key rotation, and registration replay; assert safe generic response and no account takeover.
- Two soldiers each matching one half of the claim (A by email, B by AD username), two soldiers matching the same claim in legacy/pre-constraint data, and one match that is inactive; assert `Ambiguous`, a recorded conflict, a generic user response, and no session or link.
- Duplicate personal numbers in one HR feed (identical vs. differing payloads), HR email/AD username colliding with another Soldier, and conflict re-detection on every later sync until acknowledged; assert the validation error is raised, caught per person, logged, the latest record is applied, and an admin-visible warning exists.
- Invite-code waiver can only be exercised through a live OIDC registration context; assert a forged/expired/replayed context or a plain request cannot skip the invite code.

---

## File Map

- Add shared email/AD normalization in `backend/app/services/identity.py`; update `backend/app/db/models.py`, registration, email verification, soldier update, HR sync/import, and admin mutation call sites found by repository search.
- Add Alembic revisions under `backend/alembic/versions/` for normalization/backfill constraints and OIDC identity storage; migration diagnostics must be executable before enforcing constraints.
- Add `resolve_soldier_identity` and conflict recording in `backend/app/services/identity_resolution.py`, an admin conflicts router (`backend/app/routes/identity_conflicts.py`), and HR conflict detection/resolution in `backend/app/services/hr/person_sync.py`, a new `backend/app/services/hr/conflicts.py`, and `backend/app/routes/hr_review.py`; model and Alembic additions for the conflict tables.
- Add OIDC configuration to `backend/app/settings.py`, service modules under `backend/app/auth/` or `backend/app/services/oidc.py`, and routes in `backend/app/routes/auth.py` (split router if that file becomes unmanageable).
- Update `frontend/src/api/auth.ts`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/RegisterPage.tsx`, and their tests for SSO action and locked prefilled identity fields (invite-code field hidden in SSO registration); add an admin identity-conflicts view and an HR sync conflicts tab with resolve actions in `frontend/src/pages/admin/` plus `frontend/src/api/hrReview.ts` and `he.json` strings.
- Add backend unit/integration tests under `backend/tests/unit/` and `backend/tests/integration/`; add browser coverage under `frontend/tests/e2e/` using synthetic OIDC fixtures only.

### Task 1: Define and test email plus AD username normalization

**Files:** Create `backend/app/services/identity.py`; create `backend/tests/unit/test_identity.py`.

- [x] Write parameterized failing tests for trimmed email, case normalization, canonical local-part extraction (`Dude@gmail.com` -> `dude`), blank-to-`None`, invalid addresses, absent local part, plus tags, dots, and the selected AD username character/length policy.
- [x] Confirm the intended AD username character and length limits with the chosen directory convention; encode the explicit allowed format and reject unsupported values without dropping characters.
- [x] Implement `normalize_email(value: str | None) -> str | None` and `derive_ad_username(email: str | None) -> str | None` with one shared validation path.
- [x] Run the focused identity unit tests and verify normalization is deterministic and idempotent.
- [x] Search every write path for `Soldier.email`; list registration, HR sync, imports, admin edit, self-service edit, and verification code in the plan's implementation notes before moving to the migration.

## Implementation Notes

### Task 1: identity contract and Soldier email write-path inventory

- The chosen directory convention is legacy Windows AD `sAMAccountName`: the derived local part is lowercase, at most 20 characters, and rejects `" / \\ [ ] : ; | = , + * ? < >` without removing or replacing any characters. Dots remain unchanged. The shared helper currently accepts ASCII dot-atom local parts and ASCII hostname domains; unsupported Unicode and quoted email syntax raise `ValueError` for migration preflight to report. This is a selected application email policy, not a provider alias rule.
- Registration: `backend/app/routes/auth.py` passes `RegisterRequest.email` into `backend/app/services/registration.py:register`, which creates `Soldier(email=email)`.
- HR sync: `backend/app/services/hr/mapping.py:map_hr_user` copies `HrUser.mail` into `MappedSoldierFields.email`; `backend/app/services/hr/person_sync.py:_apply_new_person` creates a Soldier, and `_apply_existing_person` assigns HR-owned fields dynamically with `setattr(soldier, field_name, new_value)`. `HR_OWNED_FIELDS` includes `email`; an HR override may skip that assignment.
- Legacy Excel import: `backend/app/routes/import_excel.py` parses email into the import row, creates `Soldier(email=row.email)` for new rows, and assigns `s.email = row.email` for updates when the row has an email.
- Import sessions: `backend/app/services/import_parsers/v1_standard.py` parses email, `backend/app/services/import_sessions.py` builds the normalized import row, creates `Soldier(email=row.get("email"))`, and assigns `s.email = row["email"]` for updates when present.
- Admin/duty-manager profile edit: `backend/app/routes/soldiers.py:update_profile` passes request fields to `backend/app/services/soldiers.py:update_soldier_profile`; `PROFILE_FIELDS` includes `email`, so its `setattr(soldier, k, v)` writes it. The basic `PATCH /soldiers/{id}` route does not accept email.
- Enrollment review edit: `backend/app/routes/enrollment.py` applies `body.email` through `_apply("email", body.email or None)`, which dynamically calls `setattr(s, field, new_value)`.
- Self-service edit: `backend/app/routes/me.py:set_email` directly assigns `user.email = new_email` and clears `email_verified` on change, then requests verification.
- Verification: `backend/app/services/email_verification.py:request_verification` snapshots `soldier.email` in `EmailVerificationToken.email`; `verify_token` compares it to the current Soldier email and sets `soldier.email_verified = True`. Its conflict lookup currently checks only other **verified** rows, so Task 3 must align it with uniqueness across verified and unverified addresses.
- Other Soldier constructors in `backend/app/services/soldiers.py:onboard_soldier` and `backend/app/scripts/{bootstrap,seed,seed_polaris,storage_migration_rehearsal_fixture}.py` do not currently set email; retain the invariant if they gain email input.

### Task 2: Preflight existing data and enforce database uniqueness

**Files:** Create Alembic migration under `backend/alembic/versions/`; add migration test under `backend/tests/unit/test_migration_soldier_identity.py`; update model/tests.

- [ ] Write migration tests with duplicate normalized emails, duplicate derived usernames from different email domains, blank values, malformed addresses, and valid rows; assert diagnostics identify conflicting soldier IDs without changing or merging data.
- [ ] Add `Soldier.ad_username` and normalized email expression/index design to the SQLAlchemy model using PostgreSQL-compatible constraints matching the chosen canonical stored values.
- [ ] Implement a preflight command/migration step that raises a clear actionable conflict report before any backfill or constraint DDL; ensure it prints addresses only where needed for operator resolution and does not run in production implicitly.
- [ ] Backfill canonical email and derived username only after preflight reports no conflicts; keep blank email as `NULL` and retain `email_verified` without using it to determine uniqueness.
- [ ] Add unique partial indexes for non-null email and AD username; test case-insensitive duplicate prevention under PostgreSQL and migration downgrade behavior.
- [ ] Extend preflight to personal numbers: report soldiers whose trimmed personal numbers collide or are blank (the raw column is already unique, so only normalized collisions are new), and add a CHECK that `personal_number` equals its trimmed form and is non-blank. Test that personal number, email, and AD username each reject a duplicate at the PostgreSQL level.
- [ ] Run migration tests and verify Alembic upgrade/downgrade on the disposable database.

### Task 3: Route every Soldier email mutation through the shared invariant

**Files:** `backend/app/services/registration.py`, `backend/app/services/email_verification.py`, soldier update service, HR person sync/import paths, admin routes/services, relevant tests.

- [ ] Add failing service tests for registration and each discovered email write path, asserting normalized `email` and derived `ad_username` are stored together.
- [ ] Refactor each write path to call the identity service, update both fields in one SQL transaction, and translate database uniqueness conflicts into stable user-facing errors.
- [ ] For email changes, clear `email_verified` and invalidate outstanding verification tokens as the current verification flow requires; roll back both fields on either email or username collision.
- [ ] Update OIDC-verified registration path so only a consumed server-side registration context can preserve the issuer's verified-email status.
- [ ] Catch `IntegrityError` on the three unique constraints at each write path and map it to a typed `IdentityCollisionError` naming the colliding field (not the other soldier); every path checks collisions first and relies on the DB only for races.
- [ ] Run focused registration, email verification, HR/import, and soldier update tests; verify no direct write bypass remains by searching assignments to `.email`.

### Task 4: Identity resolution service and admin identity conflicts

**Files:** Create `backend/app/services/identity_resolution.py`; model + Alembic migration for `identity_conflicts` (id, source `sso|hr_sync|registration`, derived AD username, personal number nullable, status `open|resolved|dismissed`, created/resolved timestamps and resolver) and `identity_conflict_candidates` (conflict id, soldier id, which fields matched); create `backend/app/routes/identity_conflicts.py`; tests under `backend/tests/unit/` and `backend/tests/integration/`.

- [ ] Write failing tests for `resolve_soldier_identity(session, email, ad_username)` returning `Match`, `NoMatch`, or `Ambiguous`, covering: exactly one soldier matching both fields; none; email matches A and AD username matches B; multiple matches in data that predates the constraints; match on only one field; inactive soldier.
- [ ] Implement the resolver as the only code that decides "who is this person"; it queries email and AD username candidates, de-duplicates by Soldier id, and never raises on ambiguity (it returns it).
- [ ] Add `record_identity_conflict(...)` that stores the conflict plus candidate soldier ids idempotently (same AD username + source reuses the open row) and emits an error-level log with soldier ids only, no email or claims.
- [ ] Add admin-only endpoints (reuse the existing admin role dependency): list open conflicts with candidates (soldier id, name, personal number, masked email), resolve with an explicit chosen soldier id (the next SSO attempt then links to it), and dismiss with a reason. Resolution is audited and never edits the other candidates implicitly.
- [ ] Test endpoint authorization (non-admin denied), idempotent recording, resolve/dismiss transitions, and that user-facing responses for an ambiguous login stay generic.

### Task 5: Add OIDC provider configuration and protocol service

**Files:** `backend/app/settings.py`, create `backend/app/services/oidc.py` (or `backend/app/auth/oidc.py`), `backend/pyproject.toml`, OIDC unit tests.

- [ ] Select a maintained OIDC library compatible with supported Python version; add its pinned dependency and verify it validates discovery, JWKS signatures, and ID-token claims.
- [ ] Add optional server settings for issuer, client ID/secret, exact redirect URI, and transaction TTL; default disabled and validate HTTPS outside local development.
- [ ] Write unit tests for code flow configuration, PKCE S256, random state/nonce, exact redirect URI, allowed signing algorithms, and verified-email requirements using a local mock OIDC provider.
- [ ] Implement discovery only from the configured HTTPS issuer; validate exact issuer, audience/authorized party, expiry, issued-at, nonce, signature, and key rotation using the library.
- [ ] Add one-time transaction persistence bound to the initiating browser session; store PKCE verifier server-side, expire quickly, and consume atomically.
- [ ] Ensure provider tokens, authorization codes, state, nonce, email, and claims are redacted from logs and never returned to the frontend.
- [ ] Run protocol unit tests against a local mock issuer and verify discovery/JWKS failure denies login without passwordless fallback.

### Task 6: Persist stable OIDC identities and complete existing-account login

**Files:** Create OIDC identity model/migration, `backend/app/routes/auth.py` or dedicated OIDC router, session issuance helpers, backend integration tests.

- [ ] Write migration/model tests enforcing unique `(issuer, subject)` and one identity row per Soldier according to the accepted schema.
- [ ] Implement start and callback endpoints with rate limits; callback consumes state transaction, validates OIDC response, requires verified email, and queries stable issuer/subject first.
- [ ] For an existing linked identity, deny inactive soldiers and otherwise call the same session issuance/cookie logic as password login.
- [ ] For a first link, call `resolve_soldier_identity` with the verified email and derived AD username. `Match` -> bind subject in a transaction and reject inactive or already-bound candidates generically. `Ambiguous` -> record an `IdentityConflict` (source `sso`), deny with the generic account-linking error, and create no session. `NoMatch` -> hand over to the registration continuation (Task 7).
- [ ] Add PostgreSQL integration tests for linked login, first link, concurrent first-link attempts, inactive account, email mismatch, existing binding elsewhere, uniqueness race, and session/cookie compatibility.
- [ ] Verify all existing role/permission checks remain unchanged and provider claims do not populate authorization fields.

### Task 7: Continue unmatched identities into registration without an activation code

**Files:** `backend/app/services/oidc_registration.py`, `backend/app/routes/auth.py` or registration router, `RegisterRequest` and registration service, backend integration tests.

- [ ] Write failing tests proving an unmatched verified subject creates no Soldier and instead creates a short-lived, single-use, browser-bound registration context.
- [ ] Implement generic callback routing to `/register` with no email, token, state, or reusable credential in query parameters; supply prefilled values through the same-origin authenticated/session context.
- [ ] Mark email and derived username read-only in the registration context. The invite/activation code is **not** required when registering from a live OIDC context (`NoMatch` result); personal number, profile eligibility, and the current password field remain required, and registration without such a context still requires the invite code. The server decides this from the stored context, never from a client flag.
- [ ] Re-run `resolve_soldier_identity` at the final registration step (not only at callback time) and refuse with a generic error plus a recorded conflict if the result is no longer `NoMatch`; enforce personal-number uniqueness there too.
- [ ] Update final registration to consume context atomically with Soldier creation and issuer/subject binding; failed validation or DB error must leave neither a Soldier nor a link.
- [ ] Confirm SSO registration uses the existing holding-node placement and enrollment approval (a commander at or above mador via `backend/app/routes/enrollment.py`), and add a test that the new soldier is in the holding node, pending, with no extra access until approved.
- [ ] Test that the invite code is skippable only with a valid context, and still enforced for plain registration and for forged, expired, or replayed contexts.
- [ ] Test replay, expiry, browser mismatch, already-owned email, already-owned personal number, concurrent consume, collision, invalid invite/personal number, successful create, and login session issuance.
- [ ] Verify error responses do not reveal whether a Soldier/email/subject exists.

### Task 8: Detect, warn about, and resolve HR sync identity conflicts

**Files:** `backend/app/services/hr/person_sync.py`, create `backend/app/services/hr/conflicts.py`, `backend/app/services/hr/errors.py`, `backend/app/routes/hr_review.py`, model + Alembic migration for HR conflicts and a `hr_preferred_records` table (reuse the Task 4 tables with source `hr_sync` if the shapes fit; add `hr_person_sync_id`, the raw HR payload per candidate, and `conflict_count` on `hr_person_syncs`), tests under `backend/app/services/hr/tests/` and `backend/tests/integration/`.

Note: `soldiers.personal_number` and `soldier_hr_profiles.personal_number` are already unique, so duplicates arrive from the HR feed (the same personal number twice, where the later record silently overwrites the earlier one today; that silent overwrite is what this task replaces with a warning) or as HR records whose email/AD username collide with a different Soldier, not as duplicate Soldier rows.

- [ ] Write failing tests: feed with the same personal number twice (identical and differing payloads), HR email that normalizes to another Soldier's email, HR email whose derived AD username belongs to a different Soldier, HR person with an invalid email, and a clean feed (no regression).
- [ ] Add `HrIdentityConflictError(ValueError)` in `errors.py` carrying the personal number and candidates. Add an explicit invariant check before `_apply_new_person`/`_apply_existing_person` that raises it, and use `.all()` rather than `scalar_one_or_none()` for the personal-number lookups so multiple rows raise the typed error, not `MultipleResultsFound`. Detect in-feed duplicates by grouping `users` by normalized personal number before the loop.
- [ ] In `run_person_sync`, catch `HrIdentityConflictError` separately from generic exceptions. For a duplicated personal number: record the conflict (status `warning`, with all candidate payloads and which one was applied) idempotently, log at warning level (ids only, no PII), increment `conflict_count`, and continue by default with the latest record (last occurrence in the feed), so earlier occurrences are not applied. For an email/AD username collision with another Soldier: apply the person's other fields, leave the colliding value unchanged, and record the same kind of warning. Never fail the run, and keep processing other people. Re-detect each sync: an unchanged, acknowledged conflict stays quiet, and one whose inputs changed reopens.
- [ ] Add `hr_preferred_records` (unique `personal_number`, `key_type`, `key_value`, chosen-by admin, chosen-at, optional note) so an admin's choice persists across syncs. The record key is the most stable identifier the HR payload offers, in priority order: `t_person_id`, then `username`, then normalized `mail`; the stored `key_type` records which one was used, and a candidate with none of them cannot be chosen.
- [ ] Add `GET /hr-review/identity-conflicts` and endpoints to acknowledge, choose, and clear the preference. Acknowledge accepts the default (latest record) for this occurrence and silences the warning. Choose takes a candidate and stores it as the preferred record for that personal number; it is only allowed for a candidate with a valid normalized email and derived AD username that collides with nothing else, otherwise a validation error. Choosing applies that candidate immediately through the normal sync write path and resolves the conflict. Clear removes the preference so the default (latest) applies again. Choosing and clearing are audited.
- [ ] Use the remembered choice on every later sync: when a personal number is duplicated in the feed and exactly one record matches the stored key, apply that record and record no warning. If no record matches (the preferred one left the feed), or more than one still matches the key, fall back to the latest record and record a warning that names the stale or ambiguous preference without deleting it. If the feed has no duplicate, the preference is ignored and kept. Re-validate the preferred record at sync time (valid email and AD username, no collisions); if it fails, fall back and warn rather than apply it.
- [ ] Tests for list/acknowledge/choose/clear, authorization, invalid pick, default-latest applied, chosen record applied on the next and later syncs with no warning, preference persisted across runs, preferred record missing or duplicated falls back and warns, clearing restores the default, choose then re-sync is clean, and the validation error surfacing in logs and the run's error/conflict counts so it can be monitored.

### Task 9: Add frontend login and registration experience

**Files:** `frontend/src/api/auth.ts`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/RegisterPage.tsx`, corresponding unit tests, E2E spec.

- [ ] Add failing tests that the SSO button appears only when the server reports OIDC availability and leaves the personal-number/password login usable.
- [ ] Implement a top-level navigation to the backend OIDC start route; do not store provider tokens or callback parameters in web storage.
- [ ] Add read-only prefilled email and AD username fields when registration resumes from OIDC context; preserve ordinary local registration fields and validation unchanged.
- [ ] Hide the invite-code field when registration resumes from an OIDC context; keep it for ordinary registration. After SSO registration, show the existing pending-approval state for holding-node soldiers.
- [ ] Add a browser test that an SSO-registered soldier is in the holding node, has no access beyond what holding-node soldiers have, and gains it only after a commander at or above mador approves.
- [ ] Add an admin identity-conflicts view listing open SSO/registration conflicts with their candidate soldiers and resolve/dismiss actions, and an HR sync conflicts tab in `HrSyncReviewContent` showing a warning for each conflict with the duplicate HR records side by side, the one applied by default (latest) marked, an "acknowledge" action, a "use this one from now on" action that remembers the choice (enabled only for candidates with a valid email and AD username), a visible "remembered choice" marker with a "clear" action, and the validation reason when a pick is invalid. Add Hebrew strings in `he.json` (grep call sites first; duplicate keys are a known hazard).
- [ ] Add safe loading/error display for cancelled/failed SSO without echoing callback data or identity details.
- [ ] Add component tests for both conflict screens (empty, list, resolve, error) and a browser test that an ambiguous SSO login shows the generic error to the user and the conflict in the admin screen.
- [ ] Add browser tests for configured/unconfigured login UI, SSO-to-registration prefill, manual registration compatibility, and no sensitive values in browser URL/storage.
- [ ] Run focused Vitest and Playwright flows against the local mock OIDC provider.

### Task 10: Security review and complete verification

**Files:** OIDC/email tests, migration, auth routes/services, frontend files, docs.

- [ ] Test the cross-check matrix end to end: SSO match, no match (registration without invite code), ambiguous (conflict recorded, no session), and HR duplicate personal numbers (validation error raised and caught, warning recorded, latest record applied, other people still synced).
- [ ] Test state, nonce, PKCE verifier, signature, `iss`, `aud`, `azp`, `exp`, `iat`, missing/unverified email, discovery outage, JWKS outage, key rotation, replay, and open redirect rejection.
- [ ] Search application logs, audit events, URLs, responses, browser storage, and test artifacts for tokens, authorization codes, state, nonce, email claims, or secrets; remove any leak.
- [ ] Run email and OIDC migrations against PostgreSQL with conflict and clean fixtures; run backend auth/registration/email suites and frontend auth tests.
- [ ] Run existing login and registration browser journeys plus new mock-provider OIDC journey; verify the legacy password flow still produces the existing session.
- [ ] Document provider configuration and local mock-provider setup without embedding production issuer URLs or credentials; explicitly state provider-specific AD syntax assumptions.

## Execution Handoff

OIDC protocol and identity linking are security-sensitive and touch overlapping email write paths. Use subagent-driven execution only after review of this plan, with one owner for shared normalization/migrations/identity resolution (Tasks 1-4, which Tasks 6-8 depend on) and one integrated reviewer for callback, registration, and frontend flow consistency.
