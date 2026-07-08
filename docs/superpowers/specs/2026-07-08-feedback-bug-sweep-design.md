# Feedback bug sweep — design

Source: a batch of feedback from technical users covering auth/session bugs,
display bugs, a broken swap-approval workflow, missing validation, a
security-relevant permission gap, and missing notifications. Nine reported
items, grouped below into independently implementable sub-projects.

## A. Frontend data freshness (react-query migration)

**Problem:** `@tanstack/react-query` is wired up globally
(`frontend/src/main.tsx`) but almost unused — most pages fetch data with a
manual `useEffect` + `useState`, with no shared cache and no invalidation on
mutation. Result: after an action changes data (e.g. approving something),
other open/other screens don't reflect it until the component remounts
(navigate away and back). This is also the root cause of section D below
needing "IDs instead of names" bugs to be tracked down per-page instead of
fixed once.

**Fix:** Full migration — every page/component that fetches data moves to
`useQuery`; every mutation (create/approve/reject/swap/update) calls
`queryClient.invalidateQueries` for the relevant query key(s) on success.
Done incrementally page-by-page (not one large diff), verifying each page
still renders correctly after migration.

**Scope:** all pages, not just the ones explicitly named in feedback.

## B. Auth session lost on page refresh

**Problem:** Refreshing the page (F5) in the same tab/session logs the user
out immediately, requiring re-login.

**Root cause:** `backend/app/settings.py:24` — `cookie_secure` defaults to
`True` (`COOKIE_SECURE` env var). This makes the browser require an HTTPS
(secure) context to store/send the `refresh_token` cookie at all. If the
active environment serves the app over plain HTTP (or the browser doesn't
treat the host as a secure context), the cookie is silently dropped after
login. On F5, the in-memory access token (a JS module-level variable,
`frontend/src/api/client.ts:10`) is wiped, and `POST /auth/refresh`
(`AuthContext.tsx:27`) has no cookie to read, so it 401s and the user is
logged out.

**Fix:**
- Verify/correct `COOKIE_SECURE` per environment (off for local HTTP dev, on
  for real HTTPS deployments, including the Tailscale funnel path).
- Add a startup/runtime warning if `cookie_secure=true` but a request arrives
  over plain HTTP, so this doesn't silently regress again.

## C. Duty-type / lookup labels showing as raw IDs

**Problem:** Duty types (and similar lookups) render as raw UUIDs instead of
display names in some views — most visibly on a soldier's own dashboard,
where their own duty entries show a generic "תורנות" with no real details.

**Root cause:** `GET /duty-config/duty-types` is gated to managers only
(`require_config_manager` → `require_duty_manager_or_admin`,
`backend/app/routes/duty_config.py:23-28`). Soldier-facing pages
(`HomePage.tsx:95`, `DutyCalendarWidget.tsx`, `SwapStatusWidget.tsx`) call it
to build an id→name map; the 403 is silently swallowed
(`.catch(() => [] as DutyType[])`), leaving an empty map, so every duty on a
soldier's own dashboard falls back to a generic label instead of the real
duty type name.

**Fix:** Open duty-type (and any similarly-gated pure lookup/label)
endpoints to any authenticated soldier — they return names only, not
sensitive data. Once section A lands, a failed lookup fetch will surface as
a visible error/retry instead of silently rendering blank, catching future
regressions of this kind.

## D. Exemption type missing when approving an exemption request

**Problem:** The exemption type doesn't show up in the approval UI for a
pending exemption request.

**Root cause:** `ExemptionRequestOut._out`
(`backend/app/routes/exemption_requests.py:38-104`) only includes
`exemption_type_id`/`reason` when `include_sensitive=True`. The
`include_sensitive` computation for the pending-approval list endpoint
(`get_pending_exemption_requests`) doesn't currently evaluate to true for
every caller who actually holds approval rights on that request.

**Fix:** Correct the `include_sensitive` gating so it's always true for a
caller with approval authority over the request, ensuring the type is
visible wherever an approval decision is being made.

## E. Swaps — broken approval workflow (full redesign)

**Problem:** Swaps don't actually swap, and no real approval request reaches
the soldier being asked to cover.

**Root cause:** The data model has two approval flags
(`requester_side_approved`, `covering_side_approved`,
`backend/app/db/models.py:494-496`), but only a manager
(`Action.SWAP_APPROVE`, granted to admin/commander/duty_manager only,
`backend/app/auth/authz.py:54,75,90`) has any endpoint/UI to set them — via
`approve_side()` on the Approvals page
(`frontend/src/pages/ApprovalsPage.tsx:209-216,469-480`). The soldier gets a
notification implying they need to act (`swap_offer`,
`backend/app/services/swaps.py:188-192`) but has no button to actually
approve/decline. Since `swaps.require_manager_approval` defaults to `true`,
every swap sits in `pending_approval` until a manager manually clicks both
sides.

**New model:**
- **2 soldier-approval flags** — `requester_soldier_approved`,
  `covering_soldier_approved`. Each soldier gets a real approve/decline
  action on their own Swaps page for their own side.
- **2 sets of chain-of-command manager approvals** — for each side
  (requester, covering), walk that soldier's `HierarchyNode.path_ids` from
  their own node up to the root of the hierarchy, collecting every distinct
  `commander_id` encountered (skipping nodes with no commander assigned).
  Every one of those commanders must individually approve that side.
  Tracked in a new table:
  `swap_manager_approvals(id, swap_request_id, side, commander_id, approved_at, decision_note)`.
  - If the same person is a commander in both soldiers' chains, they get
    **two independent approval rows** (one per side) and must approve each
    separately — no dedup across sides.
  - Chain walk goes **all the way to the root** (not depth-limited).
- **Finalization:** the swap only applies (`_apply_cover`) once both soldier
  flags are true AND every required `swap_manager_approvals` row on both
  sides is approved.
- **Rejection:** any required party (either soldier, or any commander in
  either chain) can reject the whole request; status → `rejected`, requester
  notified, remaining pending rows are moot.
- **UI:**
  - Soldier's own Swaps page: shows full 4-part-plus-chain status (own
    approve/decline action, plus read-only status of the other soldier and
    all required commanders on both sides) with ✓/✗/pending icons; names are
    clickable through to the relevant soldier profile.
  - Approvals page (managers): same status view, but each commander only
    gets an actionable approve/reject control for their own required row(s).
- `swaps.require_manager_approval` setting: when `false`, skip the manager
  chain entirely (soldier-only approval, same as today's fast path) —
  behavior unchanged for that setting's existing meaning.

## F. Validation gaps

**Problem:** No cap on exemption/constraint date ranges, and several
missing cross-field checks on soldier profile dates.

**Fix — date range cap:** exemption grants, exemption requests, and personal
constraints currently only check `end_date >= start_date`
(`backend/app/services/exemptions.py:31-32,76-77`,
`backend/app/services/exemption_requests.py:26`,
`backend/app/services/constraints.py:53-54`). Add a max-span check:
`end_date <= start_date + 364 days` (1 year minus 1 day) on all three.

**Fix — soldier profile cross-field validation:** none of
`onboard_soldier`, `update_soldier`, `update_soldier_profile`, or
`approve_field_update` (`backend/app/services/soldiers.py`) currently
validate relationships between `enlistment_date`, `discharge_date`,
`mandatory_end_date`, and `rank`. Add:
- `discharge_date > enlistment_date`
- `mandatory_end_date <= discharge_date` (when both set)
- when `rank` is a career/permanent track (קבע/קב״ה): `discharge_date` must
  not be in the past (i.e. `discharge_date >= today`)

Enforced in both the Pydantic request schemas
(`backend/app/routes/soldiers.py:55-97`) for immediate feedback, and in the
service layer so no entry point (including the field-update-approval flow)
can bypass it.

## G. Login lockout counter is effectively global

**Problem:** Failed-login rate limiting appears to affect all users, not
just the one attempting to log in.

**Root cause:** two separate mechanisms exist. Per-account lockout is
correctly scoped (`Soldier.failed_login_count`/`locked_until`,
`backend/app/routes/auth.py:136-149`). But the surrounding request rate
limiter is IP-keyed, not account-keyed:
`Limiter(key_func=get_remote_address)` (`backend/app/rate_limit.py`). Users
behind a shared IP (e.g. a base's shared internet/NAT) throttle each other's
login attempts.

**Fix:** key the login endpoint's rate limit off the submitted
`personal_number` (falling back to IP if the field is missing/malformed)
instead of solely the client IP, so the limiter tracks per-account attempt
rate rather than per-network.

## H. Enrollment/intake: missing notifications + no permission gate

**Problem (a):** Soldiers aren't notified when their קליטה למסגרת
(intake/enrollment) is approved or rejected.

**Root cause:** `backend/app/services/enrollment.py` (`approve_enrollment`,
`reject_enrollment`) only calls `write_audit`, never `create_notification` —
despite `NotificationType.enrollment_approved` /
`enrollment_rejected` already existing and being wired into frontend
notification routing.

**Fix:** call `create_notification` on both approve and reject, matching
the pattern already used in `exemption_requests.py`.

**Problem (b):** A soldier whose enrollment/intake request is still
`pending` already has a fully live account (`registration.py` creates the
`Soldier` row with `role="soldier"` immediately) and can use every
soldier-facing feature exactly like a fully onboarded soldier — nothing
checks `SoldierEnrollmentRequest.status` before granting soldier-level
actions.

**Fix:** add an authz-layer gate — while a soldier has a `pending`
enrollment request, allow read-only access (their own profile, their own
duties/data as already populated) but block write/action endpoints
(constraints, exemptions, swaps, and other soldier-initiated mutations)
until the enrollment request is `approved`. Soldiers with no enrollment
request at all (e.g. created outside the enrollment flow) are unaffected.

## I. Date format (needs reproduction, not assumed to be a code bug)

**Investigation result:** the codebase is largely consistent —
`frontend/src/utils/formatDate.ts` centralizes display as `dd.mm.yyyy`,
native `<input type="date">` fields consistently carry `lang="he"`, and
`toLocaleDateString` calls pass `"he-IL"` explicitly. No hardcoded
`MM/DD/YYYY` construction was found. The most likely explanation is a native
date-picker following the reporting user's OS/browser locale rather than a
code defect (`lang="he"` only nudges some browsers' pickers).

**Plan:** reproduce on the reporting user's actual browser/OS before writing
any fix. If the picker itself is the issue, consider a custom-rendered date
picker only if reproduction confirms it's needed — no speculative change.

## Out of scope / explicitly not doing

- No speculative fix for date format (section I) without reproduction.
- No change to `swaps.require_manager_approval`'s existing meaning beyond
  making the manager path actually work (section E).
- No broader refactor of the hierarchy/commander model beyond what section E
  needs (reusing `HierarchyNode.path_ids` / `commander_id` as-is).
