# רשנ"צ (military driving license) profile field + eligibility requirement

## Goal

Add a soldier profile property for רשנ"צ (רישיון נהיגה צבאי — military
driving license): whether the soldier holds one, and its expiry date.
Soldiers request to set/change it themselves; approval requires a commander
or duty manager, and if the approver is a commander (not a duty manager),
they must additionally be rank רסן ("Major") or above. Duty types can be
configured to require it, gating eligibility the same way `requires_bahad1`
already does.

## Backend changes

### Data model (`backend/app/db/models.py`)

Two new nullable columns on `Soldier`, alongside `bahad1_graduate`:

- `has_military_driving_license: bool | None`
- `military_driving_license_expiry: date | None`

New Alembic migration adding both columns.

### Editable-field + eligibility plumbing (`backend/app/services/eligibility.py`)

- Add `"military_driving_license"` to `SOLDIER_EDITABLE_FIELDS`. This is a
  single logical field covering both columns — the `SoldierFieldUpdate.new_value`
  (and `previous_value`) is a JSON string `{"has_license": bool, "expiry_date":
  "YYYY-MM-DD" | null}`, since the existing table stores one string per
  request and other fields (dates, gender) already round-trip through string
  encoding.
- Add `requires_military_driving_license: bool = False` to
  `DutyTypeRequirements`.
- In `_is_eligible`: block if `reqs.requires_military_driving_license` and
  either `not soldier.has_military_driving_license`, or
  `soldier.military_driving_license_expiry` is set and is in the past
  (`< today`). No expiry set + `has_license=True` counts as eligible
  (permanent license, matches how licenses without a printed expiry work).

### Request submission (`backend/app/services/soldiers.py`)

- `submit_field_update`: no change needed — already generic over
  `field_name`/`new_value` strings once `SOLDIER_EDITABLE_FIELDS` includes
  the new name.
- `approve_field_update`: add a branch for `field == "military_driving_license"`
  that `json.loads(raw)` and sets both `soldier.has_military_driving_license`
  and `soldier.military_driving_license_expiry` (parsing the date string,
  same as `last_mitvahim_date` does).
- `_get_current_value` (used to populate `previous_value` on submission):
  add a branch producing the same JSON shape from the soldier's current
  values, so history/diff rendering is consistent.

### Approval authorization (`backend/app/routes/soldiers.py`)

`approve_update` and `reject_update` currently gate on
`authorize(session, user, Action.SOLDIER_UPDATE, target_node=...)`, which
covers admins and in-scope duty managers only — `SOLDIER_UPDATE` is not in
`_COMMANDER_ACTIONS`, so commanders currently cannot act on any field-update
request.

For `upd.field_name == "military_driving_license"` specifically, extend the
allow check to also permit a commander when both hold:

- the target soldier's node is in the commander's scope
  (`_node_in_scope(target_node, scope_root_ids(session, user))`, same helper
  `routes/exemptions.py` already uses), **and**
- `commander_can_grant_commander_exemption(session, commander_id=user.id,
  commander_rank=user.rank)` from `app/services/authority.py` returns True
  (rank רסן+, or commands a מדור-level-or-above node — this is the existing
  "רסן and above" rule already used for commander-granted exemptions, reused
  as-is rather than duplicated).

All other field names keep today's behavior unchanged (DM/admin only).

## Frontend changes

### `frontend/src/pages/ProfilePage.tsx`

- Display current value near the other read-only fields (like
  `bahad1_graduate`): "✓ (expires <date>)" / "✓" (no expiry) / "—".
- Add a request row under "submit_update": a checkbox for "has license" plus
  a date input for expiry (enabled only when checked), one submit button
  that JSON-encodes both into a single `submitFieldUpdate("military_driving_license", json)`
  call — mirrors the existing per-field rows (gender/rank/phone/dates).
- The pending-updates history list is already generic over `field_name` via
  `t(\`soldier_profile.${field_name}\`)`; only needs new i18n keys and, for
  rendering `previous_value`/`new_value`, a small parse-and-format helper
  (JSON → "✓ (expires X)" text) alongside the existing `gender_*` special
  case at that render site.

### `frontend/src/components/DutyTypeRequirementsEditor.tsx`

Add `requires_military_driving_license` to the boolean-flags list, same
shape as `requires_bahad1`.

### `frontend/src/api/soldiers.ts` / `frontend/src/api/dutyConfig.ts`

Add the new fields to the corresponding TypeScript DTOs
(`SoldierDTO`/whatever carries `bahad1_graduate` today, and
`DutyTypeRequirements`).

### `frontend/src/i18n/he.json`

Under `soldier_profile`: `military_driving_license`: "רשנ״צ (רישיון נהיגה
צבאי)", `military_driving_license_expiry`: "תאריך תפוגה", plus a
`_has`/`_none` style pair if needed for the request checkbox label.

Under `eligibility`: `requires_military_driving_license`: "דורש רשנ״צ".

## Tests

- `backend/app/services/tests/test_eligibility.py` (or wherever
  `requires_bahad1` is tested): add cases for
  `requires_military_driving_license` — no license, license with no expiry,
  license with future expiry, license with past expiry.
- `backend/app/services/tests/test_soldiers.py` (or equivalent): submit +
  approve a `military_driving_license` update, assert both columns are set
  from the JSON payload; assert `previous_value` round-trips.
- `backend/app/routes/tests/test_soldiers_routes.py` (or equivalent): assert
  a duty manager can approve as before; assert a commander below רסן with
  the soldier in scope gets 403; assert a commander at רסן+ with the soldier
  in scope succeeds; assert a commander at רסן+ but with the soldier
  *out of* scope gets 403.

## Out of scope

- No dedicated two-stage approval table (unlike `ExemptionRequest`) — reuses
  the existing single-stage `SoldierFieldUpdate` flow, just with an extra
  authorization branch for this one field name.
- No background job to auto-expire or notify on upcoming expiry — expiry is
  evaluated live at eligibility-check time only, same as
  `requires_mitvahim`/`requires_alal` recency checks.
- No change to how commanders are authorized for any other field —
  `SOLDIER_UPDATE` stays a DM/admin-only action except for this one
  special-cased field.
