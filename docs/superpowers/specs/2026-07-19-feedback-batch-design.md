# Feedback batch (2026-07-16 → 2026-07-19) — design

Source: 15 feedback items from שהם, covering bug fixes, small settings/features,
and two larger workflow changes. Grouped below into independently implementable
sub-projects, ordered bugs → small features → larger features, matching the
intended implementation order (single branch off `dev`, one merge at the end).

## A. Bug fixes

### A1. Chovah/קבע consistency — rank, dates, and `is_career` are independently editable

**Problem:** Two related gaps reported together:
- A soldier can be given a discharge date before their enlistment date, or
  remain flagged as חובה (mandatory) after their `mandatory_end_date` has
  passed with no discharge_date set (or vice versa: marked קבע/is_career while
  holding a rank that is unambiguously a חובה-only rank).
- Today `is_career` (`backend/app/db/models.py:52`) is a plain boolean anyone
  can set directly (registration form `RegisterPage.tsx:53`, enrollment PATCH
  `backend/app/routes/enrollment.py:193-194`), completely independent of
  `mandatory_end_date`/`discharge_date`. Meanwhile `inferred_service_type()`
  (`backend/app/services/eligibility.py:47-56`) already computes חובה/קבע from
  those same dates for eligibility checks — so the stored flag and the
  computed value can (and do) disagree.
- `_check_soldier_dates` (`backend/app/services/soldiers.py:33-45`, from the
  `date-validation-gaps` plan) only checks discharge ≥ enlistment and
  `mandatory_end_date ≤ discharge_date` when `is_career` is already true. It
  never validates rank against career status.

**Decision (from user):** `is_career` stops being a directly-settable field.
It becomes derived from `mandatory_end_date`/`discharge_date`, the same rule
`inferred_service_type` already uses. Separately, a soldier can never be in a
state where their rank is one of the five חובה-only ranks
(`טוראי`, `רבט`, `סמל`, `סגמ`, `קמא`) while flagged/derived as קבע.

**Fix:**
- Add `CHOVAH_ONLY_RANKS = ["טוראי", "רבט", "סמל", "סגמ", "קמא"]` (exact DB
  string values, matching `ENLISTED_RANKS`/`OFFICER_RANKS` in
  `eligibility.py`).
- Replace the stored `is_career` write paths: remove it from
  `RegisterPage.tsx`'s form and from `enrollment.py`'s editable-fields body;
  compute it server-side whenever `rank`, `mandatory_end_date`, or
  `discharge_date` changes, using the same logic as `inferred_service_type`
  (קבע once `mandatory_end_date` has passed and no discharge_date closes it
  out sooner). Keep the DB column (existing eligibility/scoring code reads it
  directly) but recompute-and-store on every relevant write instead of
  trusting client input.
- At registration, before `mandatory_end_date` is known (e.g. still pending
  admin data entry), default to חובה (`is_career=False`); it flips
  automatically once dates are set/imported.
- Add validation (in the same rank/date-change path) that rejects setting
  `rank` to a `CHOVAH_ONLY_RANKS` value when the derived status is/would be
  קבע, and rejects a state where the derived status is קבע while the current
  rank is chovah-only — surfaced as a clear Hebrew validation error, not a
  silent 500.
- Extend `_check_soldier_dates` to run this rank/career consistency check
  alongside the existing date-order checks.

### A2. Missing translations: `exemption_requests.pending_commander` and swap-page duty IDs

**Problem:** Two i18n gaps reported together:
- `MyRequestsPage.tsx:380` calls `t(\`exemption_requests.${er.status}\`)`,
  and `er.status` can be `pending_commander`/`pending_duty_manager`
  (`frontend/src/api/exemptions.ts:56`), but `he.json`'s
  `exemption_requests` block (lines 390-400) only defines
  `pending`/`approved`/`rejected` — so the raw key renders.
- `SwapsPage.tsx:460,606` renders `dutyTypes[d.duty_type_id] ?? d.duty_type_id`
  — `dutyTypes` comes from a separate `listDutyTypes().catch(() => [])` call
  (line 300); any failure empties the map silently, so every duty falls back
  to the raw numeric/UUID id.

**Fix:**
- Add `pending_commander`/`pending_duty_manager` keys to `he.json`'s
  `exemption_requests` block (reuse the near-duplicate wording already at
  `he.json:176-177`).
- Have `GET /assignments/effective` return `duty_type_name` directly (as
  `SwapRequest` already does), removing `SwapsPage`'s dependency on the
  separate best-effort `listDutyTypes()` lookup for its own rendering. Stop
  silently swallowing that fetch's error where it's still used.

### A3. Missing translation: `cover_blocked.overlap`

**Problem:** `backend/app/services/swaps.py:151` raises
`SwapError(f"cover_blocked:{exc}")` where `exc` includes `"overlap"`
(`backend/app/services/assignments.py:146,266`). No frontend code translates
the `cover_blocked:*` prefix — `ApprovalsPage.tsx:41-44` and
`CoverOfferModal.tsx:39-46` only special-case `cover_not_eligible:*` — so it
renders as a raw error string when approving a cover/swap request that
overlaps an existing assignment.

**Fix:** Parse the `cover_blocked:<reason>` prefix the same way
`cover_not_eligible:` is handled, and add matching `he.json` entries (at
least `cover_blocked.overlap`; audit `assignments.py` for any other reason
strings that can flow through the same prefix).

### A4. "Missing token" when viewing exemption request images

**Problem:** `download_exemption_file` (`backend/app/routes/
exemption_requests.py:463-490`) requires a Bearer token via
`get_current_user`. `ApprovalsPage.tsx:358-362` renders the file link as a
plain `<a href=... target="_blank">`, which is a raw browser navigation and
never goes through the axios instance that attaches the token
(`frontend/src/api/client.ts:20-22`). The browser's unauthenticated GET
401s, which surfaces to the user as "missing token".

**Fix:** Fetch the file via the authenticated `api` client
(`responseType: 'blob'`), then open a generated `URL.createObjectURL(...)`
in a new tab instead of linking directly to the API URL. Revoke the object
URL after use.

### A5. Phantom pending-approval entries

**Problem:** Two independent causes surfacing as the same symptom (UI shows
a pending request that doesn't really exist):
- `commander_dashboard.py:108-115` (`summary_cards`, `pending_swaps` count)
  filters `SwapRequest.status == "pending"` — that literal value never
  exists on `SwapRequest` (real values are `open`/`pending_approval`/
  `applied`/`rejected`/`cancelled`, per `swaps.py:60,185,199`), so the count
  is always wrong/stale.
- `soft_delete` (`backend/app/services/soldiers.py:182-194`) only sets
  `left_at` on a soldier; it never cancels that soldier's own in-flight
  pending exemption-requests/swaps/field-update requests. Those keep showing
  as pending indefinitely with no live owner once the soldier is gone.

**Fix:** Correct the `SwapRequest.status` literal used in the summary-card
count. On `soft_delete`, cancel (not delete) any pending requests owned by
that soldier — exemption requests, swap requests, personal-constraint
requests — so they stop appearing as open approvals.

### A6. Soldier's own duty shows only "תורנות" with no details

**Problem:** `DutyCalendarWidget.tsx:44` and `SwapStatusWidget.tsx:40` fall
back to the literal string `"תורנות"` when `typeNames[d.duty_type_id]` /
`s.duty_type_name` is missing. `typeNames` comes from `HomePage.tsx:58,95`
calling `listDutyTypes().catch(() => [])` — the same silent-failure pattern
as A2, plus: a duty type that's since been deactivated/deleted is excluded
from the active list, so even a successful fetch can miss it.

**Fix:** Same underlying fix as A2 — stop relying on a second best-effort
lookup call for identifying the soldier's own duties; have the
assignment/effective-duty API embed the duty type name directly so it's
always present regardless of the duty type's current active/deleted state.

### A7. Frontend crash requesting a swap by (invalid) personal number

**Problem:** `AskSwapModal` in `SwapsPage.tsx:152-221` sends the raw
personal-number text input as `target_soldier_id`
(`backend/app/routes/swaps.py:57` expects a `uuid.UUID`). A non-UUID value
causes FastAPI to return a 422 with an **array** of Pydantic error objects
as `detail`. `handleSubmit` (lines 174-177) does
`setError(detail ?? "שגיאה")` without checking its type, then renders
`{error}` directly in JSX (line 212) — React throws rendering a non-string
child, and with no `ErrorBoundary` anywhere in the app, this crashes the
whole page.

**Fix:**
- Replace the raw personal-number text field with the existing
  `SoldierSearchAutocomplete` component (resolves to a real soldier id
  before submit, same pattern used elsewhere), removing the invalid-UUID
  case entirely.
- Defensively coerce any non-string `detail` (array/object) to a string
  before `setError`, as a general safety net for this error-handling
  pattern elsewhere in the app.
- Add a top-level `ErrorBoundary` around the app shell so a future unhandled
  render error degrades to an error screen instead of a blank crash.

## B. Small settings/features

### B1. Export/import for system settings

**Problem:** `config_export.py` already exports/imports reference data
(duty types, locations, hierarchy, exemption types) as Excel — but the
key/value `SystemSetting` table (`system_settings.py`, e.g. algorithm
tuning knobs, approval-requirement toggles) has no export/import at all.

**Fix:** Add `GET /admin/system-settings/export` returning the full
key→value map as JSON, and `POST /admin/system-settings/import` accepting
the same JSON shape and applying it through the existing `set_setting`
path (so validation — e.g. the `t`/`r` density checks already in
`update_settings` — still runs). Add matching buttons to
`SystemSettingsPage.tsx`. `_HIDDEN_KEYS` stays excluded from both export and
import. This is a separate JSON-based flow from the Excel `config_export`
flow — different table, different shape.

### B2. Default email-hint system setting

**Problem:** No way to nudge soldiers toward a house email domain (e.g.
`@gmail.com`) at registration or email change; `RegisterPage.tsx`'s email
field (line 185-186) is a bare `<input type="email">` with no hint.

**Fix:** Add a system setting `registration.email_domain_hint` (string,
empty = disabled) alongside the existing settings groups in
`SystemSettingsPage.tsx`. When set, show it as placeholder/suffix text on
the email field in both `RegisterPage.tsx` and wherever email change happens
(`ProfilePage.tsx`). Purely a UI hint — does not restrict what the soldier
can actually type/submit.

### B3. No notification when a request is rejected

**Problem:** `NotificationType` already defines rejection variants
(`constraint_rejected`, `exemption_rejected`, `swap_rejected`,
`enrollment_rejected` — `notifications.py:37-53`) with frontend routes
mapped, but the feedback indicates soldiers aren't actually receiving one in
at least some rejection paths.

**Fix:** Audit every reject endpoint (constraints, exemption requests,
swaps, enrollment) and confirm each one calls `create_notification(...,
type=..._rejected)` on the actual rejection path — not just on approval.
Wire up any path found missing it. Write a regression test per request type
asserting a notification row is created on rejection.

### B4. Login page doesn't show attempt count against the limit

**Problem:** `auth.py`'s `/login` only returns a bare 401
`invalid_credentials` on a wrong password (lines 167-188), with no attempt
count — the frontend (`LoginPage.tsx`) only has something to show
(`retryAfterSeconds` via the `Retry-After` header) once the account is
already locked (429, after `_LOCKOUT_THRESHOLD` failures). There's no
"attempt Y of N" feedback on the way there.

**Fix:** Have the 401 response include the current `failed_login_count` and
`_LOCKOUT_THRESHOLD` (e.g. in the JSON body). `LoginPage.tsx` shows "ניסיון
Y מתוך N, לאחר מכן נעילה" on each failed attempt, and keeps the existing
"נסה שוב בעוד X שניות" once locked — both pieces of information visible
together rather than only the lockout message.

## C. Larger features

### C1. System setting to restrict swaps to within a hierarchy level

**Problem:** Swaps can currently be requested with any soldier system-wide;
there's no way to scope them to a hierarchy level (e.g. only within the same
ענף, or only within the same מרכז).

**Decision (from user):** A global system setting, not per-node — admin
picks a hierarchy level (from `hierarchy_level_types`,
`backend/app/db/models.py:114`), and swap target/search is restricted to
soldiers sharing an ancestor node at that level with the requester. Empty/
unset = no restriction (today's behavior).

**Fix:**
- Add setting `swaps.restrict_to_hierarchy_level` (string, one of the
  configured level names, default empty/none) to `SystemSettingsPage.tsx`
  and the settings schema.
- In the swap-target search/eligibility path (`swaps_eligibility.py`,
  swap-creation validation in `swaps.py`), when the setting is non-empty,
  resolve both soldiers' ancestor node at that level (`HierarchyNode.level`)
  and reject/filter out candidates that don't share it.
- Surface the restriction in the UI (disable/hide out-of-scope soldiers in
  the target picker) rather than only rejecting on submit.

### C2. System setting to fully disable Telegram

**Problem:** No kill-switch exists — `TelegramSetupPage.tsx`,
`TelegramBadge.tsx`, and the notification service's Telegram delivery
(`notifications.py`) are always active regardless of whether the
organization wants to use Telegram at all.

**Decision (from user):** Full kill-switch — hides all Telegram UI and
stops all Telegram delivery, regardless of any individual soldier's
existing link/preference.

**Fix:**
- Add setting `telegram.enabled` (boolean, default true — preserves current
  behavior) to `SystemSettingsPage.tsx`.
- Backend: gate Telegram sending in `notifications.py`'s delivery path
  (`send_telegram_notification` or equivalent, ~line 152-190) behind this
  setting; also gate the `registration.telegram_required` setting (already
  in `system_settings.py`) — force it off when Telegram is disabled overall,
  since it can't be required if it's unavailable.
- Frontend: hide `TelegramSetupPage`'s route/nav entry, `TelegramBadge`, and
  any Telegram notification-preference toggles when the setting is off
  (fetch it via the existing public-settings mechanism used elsewhere,
  `public_settings.py`).

### C3. Commander dashboard: transfer to a specific hierarchy node, with receiving-side approval

**Problem:** In commander-dashboard entry/exit management, a commander can
only move a soldier to "the whole hierarchy" (root), not a specific
sub-node. There's also no approval step from the destination side — a
transfer takes effect unilaterally from the originating commander's action.

**Decision (from user):** Allow picking any specific destination hierarchy
node, not just the root. The transfer becomes a request, not an immediate
move: it requires approval from **either** the commander **or** the
duty-manager of the destination node before the soldier actually moves.

**Fix:**
- Extend the transfer UI in the commander dashboard to pick any
  `HierarchyNode` (existing hierarchy picker component,
  `HierarchyTree.tsx`), not just top-level.
- Model the transfer as a new pending-request type (similar shape to
  existing exemption/swap/constraint requests): created in `pending` state
  scoped to the destination node, visible to that node's commander(s)
  (`HierarchyNode.commander_id`) and duty managers
  (`DutyManagerScope`), either of whom can approve or reject.
  On approval, apply the soldier's hierarchy-node change (existing move
  logic in `commander_dashboard.py`/`hierarchy.py`); on reject, no change,
  soldier stays put, originating commander notified.
  On creation, notify the destination node's commander(s)/duty managers
  (new `NotificationType`, e.g. `transfer_request_pending`) the same way
  other pending-approval types already notify their approvers.
- The existing "move to whole hierarchy" action's behavior is unaffected
  scope-wise, but should go through the same approval step for consistency
  (root node's commander/duty-manager approves) rather than being a special
  unapproved case.

## Cross-cutting notes

- A2/A6 share a root cause (silent-fail lookup fallback pattern for duty
  type names) — fixed once via the "embed the name in the API response"
  approach rather than patched per-widget.
- A1 and C3 both touch hierarchy/soldier-state transitions; no shared code
  path, safe to implement independently.
- None of these require an Alembic migration except C3 (new request/table
  or reuse of an existing generic "pending request" pattern — plan should
  check whether the codebase already has one generic enough to extend
  before adding a new table).
