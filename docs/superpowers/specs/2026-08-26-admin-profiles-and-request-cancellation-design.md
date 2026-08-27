# Admin profiles, role promotion, and privileged request cancellation

## Goal

Allow administrators to edit all existing soldier profile fields, promote a
person to administrator from the People page with password reauthentication,
and give sufficiently senior commanders and duty managers controlled
cancellation authority over personal exemptions and constraints.

## Authorization rules

- Administrators may edit every existing profile field, including rank,
  rank-track/general rank, officer status, and next-rank date.
- Only administrators may promote a soldier to the administrator role.
  Promotion requires the acting administrator's current password and an
  explicit confirmation in the UI.
- Cancellation authorization is scoped to the target soldier's hierarchy:
  commanders at מדור or above, duty managers at ענף or above, and
  administrators may cancel both pending and approved exemption/constraint
  records.
- Approved cancellation requires a mandatory reason and the extreme-action
  warning modal. Pending records use the existing pending cancellation behavior
  while applying the same server-side authorization rule.
- Only commanders at מדור or above may perform the commander approval step for
  personal exemptions and constraints. Existing duty-manager approval rules are
  unchanged.

## Backend design

Use shared authority predicates for cancellation and commander approval. Apply
them in endpoints and service calls, and return capability fields such as
`can_cancel` from list/detail APIs so the frontend cannot infer authorization
from coarse role flags. Approved cancellation must persist actor, timestamp,
and reason, remove the record from eligibility, write an audit entry, and send
the reason in the user's notification. Personal-constraint history must expose
the cancellation reason alongside existing exemption revocation metadata.

Add a dedicated admin-only role-promotion endpoint. It verifies the current
password server-side, updates the role, and writes an audit entry. Passwords
are never logged or persisted in audit context.

## Frontend design

The admin profile editor enables all profile fields already represented by the
profile API, including rank and next-rank date. The People/person modal adds a
make-admin action that opens a password-and-confirmation modal.

Exemption and personal-constraint cards render cancellation buttons from the
server-provided capability. Approved records open a warning/reason modal;
pending records retain the existing pending cancellation interaction. History
and notifications display the supplied cancellation reason.

## Verification

Backend tests cover profile/rank editing, password-protected promotion,
hierarchy thresholds, pending and approved cancellation, reason persistence and
notification/history visibility, and commander approval thresholds. Frontend
tests cover admin profile fields, promotion confirmation, cancellation modal
behavior, and approval/cancellation button visibility. Run focused backend and
frontend tests, frontend typecheck, and lint for touched code.
