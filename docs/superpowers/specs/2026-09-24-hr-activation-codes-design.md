# HR Activation Codes (Subsystem 5 of HR Integration) — Design

## Context

Subsystem of the larger HR integration project (see
[2026-09-22-hr-api-client-design.md](2026-09-22-hr-api-client-design.md)
for the roadmap). Subsystems 1-4 (HR client, field mapping, hierarchy sync,
person sync engine) are already built and merged to `dev`.

This document specs **subsystem 5**: the security-critical activation
mechanism that turns an HR-created `Soldier` row (placeholder password, no
real credentials — subsystem 4) into a usable account, without letting a
generic invite code claim it. A commander at a configurable hierarchy level
("mador head") generates a one-time, soldier-bound code; the soldier
activates by entering it as their password on the normal login screen;
first activation forces a real password and a Justice-only intake form
(food, mitvahim/alal dates, exemptions, constraints).

## Non-goals

- Admin review UI, cron wiring (subsystem 6).
- Changing anything about the existing generic `RegistrationInviteCode`
  flow — it keeps working unchanged for non-HR people.
- Bypassing exemption/personal-constraint approval — first-login-submitted
  exemptions/constraints still require commander approval, same as every
  other submission path in the app.

## Storage: `soldier_activation_codes`

Modeled on `PasswordResetToken` (soldier-bound, single-use via `used_at`,
time-limited via `expires_at`) rather than `RegistrationInviteCode`
(unbound counter, wrong shape for this):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `soldier_id` | UUID, FK → `soldiers.id`, `ondelete="CASCADE"` | |
| `code` | Text, unique | 8-char uppercase+digits, same generator shape as `RegistrationInviteCode._generate_code` (`secrets.choice`) — short enough to hand-write/type, unlike a long hex token. |
| `expires_at` | timestamptz | `now() + hr_activation.code_expiry_days` days at creation. |
| `used_at` | timestamptz, nullable | Single-use marker, same pattern as `PasswordResetToken.used_at`. |
| `created_by` | UUID, FK → `soldiers.id` | The generating commander. |
| `created_at` | timestamptz | |

Generating a new code for a soldier invalidates any prior unused code for
that same soldier (set its `used_at = now()` without it ever being
"activated" — or simply delete it; implementation detail, either way only
one live code per soldier at a time), mirroring `password_reset`'s
`_create_reset_token` behavior of invalidating prior unused tokens.

## New settings

- `hr_activation.min_commander_level` (`SystemSetting`, default `"group"`)
  — the minimum `HierarchyLevelType.key` a commander must sit at (or above)
  to generate activation codes, read the same try/except-`SettingNotFound`
  fallback way `mitvachim.excusal_approve_min_commander_level` already is.
- `hr_activation.code_expiry_days` (`SystemSetting`, default `7`) — how
  many days a generated code stays valid before expiring unused.

## Generation: `POST /soldiers/{soldier_id}/activation-code`

Authorization (mirrors `_authorize_excusal_decision`'s pattern exactly):
caller is `admin`, or a commander whose scope (`scope_root_ids`) covers the
target soldier's `hierarchy_node_id` (`dm_scope_covers_target`) at or above
`hr_activation.min_commander_level`.

Eligibility (the security boundary this subsystem exists to enforce):
target soldier must have a linked `SoldierHrProfile`
(`soldier_id IS NOT NULL`, confirming they came from HR sync, not manual
enrollment) **and** `hr_onboarding_completed_at IS NULL` (haven't already
activated). Anyone else (already-activated, or never HR-sourced) →
rejected — this endpoint is not a general-purpose "reset anyone's
password" tool.

Returns the generated `code` in the response (shown once to the commander,
who hands it to the soldier in person — not emailed/texted, matching the
in-person handoff the product brief describes).

## Login integration

`app/routes/auth.py`'s existing `login()` gets one additive branch: after
`verify_password(password, soldier.password_hash)` fails, check whether
`password` matches an unexpired (`expires_at > now()`), unused
(`used_at IS NULL`) `soldier_activation_codes` row for that soldier
(`code == password`, plaintext lookup — same as `PasswordResetToken.token`,
no hashing needed for a short-lived single-use secret). If it matches:
consume it (atomic `UPDATE ... WHERE ... RETURNING`, same pattern as
`consume_invite_code`) and proceed exactly like a normal successful login
— same JWT issuance, same response shape (`must_change_password` is
already `True` from subsystem 4's placeholder-password creation, so
`require_password_changed` immediately blocks everything except
`/auth/change-password`). A wrong code counts as a failed login attempt
under the existing `failed_login_count`/lockout logic, same as a wrong
password — no new rate-limiting mechanism needed.

## First-login onboarding: `POST /auth/first-login-onboarding`

Self-only route, gated by `get_current_user` + `require_password_changed`
(makes sense only after a real password is set) but explicitly **not**
behind `require_hr_onboarding_complete` — this route is how that gate gets
cleared.

Fields collected (Justice-only, per the product brief — not HR-owned
fields, which sync already populated): `food_type`, `food_constraints`,
`last_mitvahim_date`, `last_alal_date`, `exemption_requests: list[dict]`,
`personal_constraints: list[dict]`.

`food_type`/`food_constraints`/`last_mitvahim_date`/`last_alal_date` are
set directly on the caller's own `Soldier` row. `exemption_requests`/
`personal_constraints` are created as pending rows
(`status="pending_commander"`) — **not** auto-granted — mirroring
`registration.register()`'s exact inline validation/creation logic
(`ExemptionType` existence check, `is_commander_exemption` rejection,
date-range validation, `validate_personal_constraint`) verbatim, since
first-login intake is still onboarding-shaped, not a change to an
already-active profile, but exemption/constraint approval is an existing
product rule this subsystem doesn't get to bypass.

On success: `soldier.hr_onboarding_completed_at = now()`.

## New dependency: `require_hr_onboarding_complete`

Modeled on `require_password_changed` (`app/auth/deps.py`). Blocks a
request only if the current soldier has a linked `SoldierHrProfile`
**and** `hr_onboarding_completed_at IS NULL` — a soldier with no
`SoldierHrProfile` (self-registered, Excel-imported, etc.) is never
blocked by this dependency, since the column is simply irrelevant to them.
Added alongside `require_password_changed` on the same broad set of
protected routes it already guards.

## `Soldier` model addition

`hr_onboarding_completed_at: datetime | None`, nullable, default `None`.
`NULL` for every soldier except one who both came through HR sync and has
completed the first-login form.

## Testing plan (TDD)

Fixture/DB-layer (testcontainers), matching this project's established
per-subsystem pattern:

1. Code generation: authorized commander (at/above configured level,
   scope covers target) → code created, prior unused code invalidated.
2. Code generation: commander below the configured level → rejected.
3. Code generation: commander whose scope doesn't cover the target node →
   rejected.
4. Code generation: target has no `SoldierHrProfile` → rejected.
5. Code generation: target already has `hr_onboarding_completed_at` set →
   rejected.
6. Login: correct activation code → succeeds, code consumed
   (`used_at` set), JWT issued, `must_change_password` still `True` in
   response.
7. Login: expired code → normal login failure (counts against lockout).
8. Login: already-used code → normal login failure.
9. Login: code for a DIFFERENT soldier's personal_number → normal login
   failure (never cross-matches).
10. First-login onboarding: sets the four direct fields, creates pending
    exemption/constraint rows, sets `hr_onboarding_completed_at`.
11. First-login onboarding: invalid exemption/constraint payload → same
    validation errors as `register()`'s equivalent cases.
12. `require_hr_onboarding_complete`: blocks an HR-linked soldier with
    `hr_onboarding_completed_at IS NULL`; does not block a soldier with no
    `SoldierHrProfile`; does not block one who's completed onboarding.

Target: 100% coverage of the new service-layer code (activation-code
generation/consumption logic, first-login onboarding logic, the new
dependency).

## Open questions to resolve during implementation (not blocking the plan)

- Exact route/module placement for the new activation-code generation and
  first-login-onboarding logic (new service file(s) under
  `app/services/` vs. extending `invite_codes.py`/`registration.py`) —
  a plan-writing decision, not a design one; either is consistent with
  existing conventions.
