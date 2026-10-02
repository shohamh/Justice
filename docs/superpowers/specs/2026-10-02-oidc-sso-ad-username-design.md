# OIDC Single Sign-On and AD Username — Design

Date: 2026-10-02  
Roadmap element: F  
Status: Spec approved by user; implementation plan prepared.

## Context

Justice currently authenticates with a personal number and password. `Soldier`
has a nullable `email` and an `email_verified` flag, but email is not database
unique. Email verification only rejects an address already verified on another
soldier. Public registration is an existing multi-step flow requiring an
invite code, personal number, profile details, and a password.

The product requirement is to add OIDC single sign-on while retaining current
login during rollout. Each soldier needs an AD username derived from the
username portion of their email address; for example, `dude@gmail.com` maps to
`dude`. An authenticated OIDC identity that cannot be matched to an existing
soldier must continue into the existing registration flow with the verified
email and derived username prefilled.

## Goals

1. Add a provider-configurable OIDC login for an existing Justice soldier.
2. Add a database-backed, normalized unique email invariant and a unique
   email-derived `ad_username` property on soldiers.
3. Link a successfully authenticated external identity to the soldier using
   the OIDC issuer and subject, then use that stable identity for subsequent
   logins.
4. Continue an unregistered authenticated user into the registration flow with
   the verified email and derived username prefilled and no invite code, while
   keeping the personal-number and profile requirements.
5. Issue the existing Justice access token and refresh-cookie session only
   after a successful account match or completed registration.
6. Keep local password login and its recovery flows available during rollout.

## Non-goals

- Auto-provisioning a Soldier row directly from an OIDC callback.
- Replacing Justice authorization roles or deriving permissions from IdP
  groups.
- Using provider access tokens to call Graph, directory, or other provider
  APIs.
- Supporting arbitrary tenant discovery or user-selected issuer URLs.
- Removing personal-number/password login in this workstream.
- Syncing arbitrary profile data or group membership from the IdP.

## Identity data model

### Email and AD username

Normalize email by trimming surrounding whitespace and applying
case-insensitive canonical comparison. Preserve the canonical address in the
`Soldier.email` field. `NULL` remains allowed for soldiers without email; blank
strings are normalized to `NULL` and do not participate in uniqueness.

Add a database-enforced unique index on normalized non-null email. Add
`Soldier.ad_username`, derived from the email local part, normalized to
lowercase. Add a database-enforced unique index on non-null `ad_username`.
Do not apply provider-specific alias rules such as stripping `+tags` or dots.
Updating a soldier email recalculates its AD username within the same database
transaction. Registration, HR sync, imports, admin edits, and self-service
email updates all use the same normalization and collision rules.

Before adding constraints, a migration preflight reports duplicate normalized
emails, duplicate derived usernames, blank/malformed addresses, and values
that cannot produce a supported AD username. The migration must not merge,
rename, or arbitrarily select a soldier. Resolve collisions explicitly before
the unique constraints are applied. Email uniqueness applies to verified and
unverified email values alike.

### External identity

Persist the configured OIDC issuer and `sub` as an external identity linked to
one Soldier. Enforce uniqueness on `(issuer, subject)` and prevent one
configured external identity from being attached to multiple soldiers. Do not
use email or `preferred_username` as the lasting identity key. A changed email
does not silently reassign the issuer/subject link.

The initial release configures one trusted issuer through server-side
configuration. A later multi-provider feature would require an explicit
provider identifier and issuer allowlist; it is not part of this design.

## Sign-in and registration flows

### Existing linked identity

1. The login page offers an SSO action only when OIDC is configured and enabled.
2. The backend starts an authorization-code flow and stores a one-time
   transaction bound to the browser session.
3. The callback validates the complete OIDC response and ID token.
4. The backend looks up the configured issuer and validated subject. If the
   linked soldier is active, issue the existing Justice session and record a
   privacy-minimal audit event.
5. If the linked soldier has left service or is otherwise disabled, deny login;
   do not trust stale provider sessions to reactivate a Justice account.

### First sign-in for a soldier already in Justice

After validating the OIDC response, require an email claim that the configured
issuer asserts is verified. Derive the canonical email and AD username on the
server. Match an existing soldier by the unique AD username and require the
soldier's canonical email to match the verified OIDC email. If the soldier has
no external identity, bind `(issuer, sub)` transactionally and issue the
Justice session. If the external identity is already bound elsewhere, the
username/email disagree, or the candidate is inactive, deny and direct the
user to support; never silently rebind identities.

If the user is already linked to another subject or a conflicting email, do
not reveal account details in the unauthenticated response. Emit a safe audit
event and show a generic account-linking error.

### No matching soldier

If no Soldier matches the verified email-derived AD username, complete the
OIDC callback without creating an account. Create a short-lived, single-use
server-side registration context and route the user into `/register` with the
verified email and derived username displayed as prefilled, non-editable
identity values. Do not put an ID token, access token, email address, or
reusable registration credential in the URL.

Registration reached this way does **not** require an invite/activation code:
the verified, server-held OIDC context replaces it. The personal number and
current profile/eligibility fields are still required (ordinary registration
keeps the invite code), and the final step re-runs identity resolution. The
new soldier is placed in the holding node by the existing registration path and
has no further access until a commander at or above mador approves them through
the existing enrollment approval flow. Its password requirement stays
in place during this rollout. The final registration request consumes the
one-time OIDC registration context and atomically creates the Soldier and
links `(issuer, sub)`; a failed registration leaves no account or partial
identity link. A used, expired, or browser-mismatched context cannot be replayed.

If the registration email is already owned by a different soldier, preserve
the unique-email constraint and stop with a generic support-directed response;
do not attach the new OIDC subject to that account solely because the address
matches.

## Identity cross-check and conflicts

Personal number, normalized email, and derived AD username are each unique in
PostgreSQL. A single shared resolver takes the verified email and derived AD
username and returns `Match` (exactly one soldier whose email and AD username
both equal the claim), `NoMatch`, or `Ambiguous` (more than one candidate, or
different soldiers matching each field). `Ambiguous` never signs anyone in or
creates a soldier: the user sees a generic error and an admin-visible identity
conflict listing the candidate soldiers is recorded, which an admin resolves by
choosing a soldier or dismisses.

### HR sync conflicts

`soldiers.personal_number` is already unique, so duplicate personal numbers come
from the HR feed (one number twice) or from HR emails/AD usernames that collide
with a different soldier. Sync raises a typed `HrIdentityConflictError`
(validation error), which the sync catches and records as an admin-visible
warning with all candidate records. It never fails the run and never overrides
silently. For a duplicated personal number the sync continues by default with
the latest record (last in the feed); admins can acknowledge that, or pick one
candidate with a valid email and AD username as the remembered choice. The
choice is stored per personal number, keyed by the record's most stable HR
identifier (`t_person_id`, then `username`, then normalized `mail`), and is
used by every later sync with no further warning. If the remembered record
disappears or stops being valid, the sync falls back to the latest record and
warns; an admin can clear the choice at any time. An HR email or AD username that collides with a different soldier is
not applied: the person's other fields sync and the colliding value is left
unchanged, with the same warning.

## OIDC protocol and security requirements

- Use a maintained OIDC client library for discovery, authorization-code
  exchange, signature/JWKS handling, and ID-token validation. Do not implement
  cryptographic token validation manually.
- Use Authorization Code flow with PKCE `S256`, transaction-specific `state`
  and `nonce`, exact registered redirect URI, and short expirations. Bind the
  transaction to the initiating browser and consume it once.
- Obtain metadata only from the configured HTTPS issuer. Validate the returned
  issuer exactly; reject arbitrary callback issuers, discovery URLs, JWKS URLs,
  redirect targets, and user-supplied endpoint values.
- Validate ID-token signature using issuer JWKS and an explicit asymmetric
  algorithm allowlist; validate `iss`, `aud`, `azp` when applicable, `exp`,
  `iat`, nonce, and any required token-type rules. Handle key rotation using
  bounded JWKS refresh and fail closed when verification is unavailable.
- Require a verified email claim from the trusted issuer before username
  derivation or account linking. If the configured provider cannot make that
  assertion, login and registration linking remain disabled until a trusted
  provider claim or verified mapping is configured.
- Discard provider tokens after authentication. Never expose them to frontend
  JavaScript, store them as Justice session tokens, or log them.
- Use HTTPS in non-local deployments. Callback cookies must be `HttpOnly`,
  `Secure` when HTTPS is enabled, and use an appropriate `SameSite` policy for
  the top-level IdP redirect. Reject open redirects and callback CSRF.
- Rate-limit flow starts and callbacks. Redact codes, tokens, state, nonce,
  email, and claims from logs and audit payloads.
- Keep the OIDC button and routes disabled when issuer/client configuration is
  absent or invalid. Do not fall back from a failed OIDC verification into a
  passwordless login.

## Email update behavior

Email changes are atomic with the derived username. Normalize and validate the
new address, check both unique constraints, clear local `email_verified`, and
invalidate outstanding local verification tokens as the current flow does.
The AD username is recalculated in the same transaction. If a collision
occurs, reject the change with a stable error and leave both values unchanged.
For email set by a validated OIDC registration context, persist the issuer's
verified status; ordinary local email changes continue to require the existing
email-verification flow.

## Compatibility and rollout

The feature is optional and disabled by default until provider configuration
is complete. Password login, activation codes, refresh, logout, and password
reset remain supported. Database migration must report conflicts before
enforcing unique email and AD username constraints. Existing API responses
must not start exposing identity tokens or unnecessary OIDC claims. No
production issuer, client secret, or deployment environment is selected in
this design.

## Acceptance criteria

1. Unique normalized email and unique derived AD username are enforced by
   PostgreSQL, with migration diagnostics for existing conflicts.
2. Soldier creation and every email update path keep `ad_username` derived
   consistently; conflicts do not partially update a soldier.
3. Valid linked OIDC users receive the existing Justice session and retain
   their existing roles and permissions.
4. Missing OIDC identity routes to the existing registration flow with email
   and username prefilled; no Soldier or external identity is created until
   successful registration.
5. SSO registration needs no invite code but keeps personal-number checks and
   consumes the OIDC registration context exactly once; plain registration
   still requires the invite code.
6. Ambiguous SSO identities and HR duplicate personal numbers are recorded as
   admin-visible conflicts and raise a typed validation error. Ambiguous SSO
   logins are denied until an admin resolves them; HR duplicates continue with
   the latest record and warn the admin, who can override.
7. Duplicate, unverified, malformed, colliding, inactive, mismatched, and
   already-bound identities fail safely without account takeover or
   enumeration.
8. Tests cover state/nonce/PKCE failures, token signature and claim failures,
   discovery/JWKS failure and key rotation, callback replay, email/username
   collisions, database races, registration resume, and existing password
   login compatibility.
9. Security review confirms tokens and PII are absent from URLs, logs, test
   reports, and browser storage.

## Standards references

- OpenID Connect Core 1.0, including ID-token validation and subject identity:
  <https://openid.net/specs/openid-connect-core-1_0.html>
- OAuth 2.0 Security Best Current Practice, RFC 9700:
  <https://www.rfc-editor.org/rfc/rfc9700.html>
- PKCE, RFC 7636:
  <https://www.rfc-editor.org/rfc/rfc7636.html>

