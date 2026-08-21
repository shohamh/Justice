# UX Audit — Findings & Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task, once
> the human has picked which tier(s) to act on. This document is a **findings-and-priorities
> report for review**, not a ready-to-run task list — several items need a product decision
> before a fix can be written.

**Goal:** Surface concrete usability papercuts across the soldier / commander / duty-manager
surfaces (swap requests, approvals, notifications, range scheduling) so the team can decide
what to fix before the system goes to production, and give enough evidence (file:line,
reproduction steps) that a follow-up implementation plan can be written without re-discovering
any of this.

**Method:** Hands-on walkthrough of the running dev app as three personas (plain soldier,
commander, duty manager — real seeded accounts, not synthetic data) via browser automation,
cross-checked against the database; plus a targeted code-reading pass over
`frontend/src/pages`, `frontend/src/components`, `backend/app/routes`, and
`backend/app/services` focused on swaps, approvals, notifications, and range (מטווח)
scheduling.

---

## How to read this doc

Each finding has: what's wrong, how it was confirmed, why it matters (who hits it, how
often), and a suggested fix. Findings are grouped into three tiers by effort-to-impact, not
by area — the idea is to knock out Tier 1 in a single short pass, treat Tier 2 as a normal
sprint's worth of polish, and treat Tier 3 as needing a product conversation first.

---

## Tier 1 — Quick fixes, high daily impact

### 1.1 Commander/DM "pending approvals" badge undercounts — excludes swaps entirely
**File:** `frontend/src/components/UnifiedNav.tsx:102-114`
`pendingCount` sums personal-constraint, exemption, field-update, enrollment, and
hakpaza pending counts — it never calls the swap pending-count endpoint. But
`ApprovalsPage.tsx:202-203,477-481` has a full "swaps" (החלפות) tab that's part of the same
approvals page. Result: the number every commander/DM glances at daily (the "פעולות מפקד"
bell / sidebar badge) can read **0** while swap approvals are sitting there waiting.
**Impact:** every commander and duty manager, every day the swap feature is used.
**Fix:** add the swap pending count into the same aggregation in `UnifiedNav.tsx`.

### 1.2 "בקש החלפה" silently does nothing when a request already exists
**Confirmed live:** logged in as soldier `1000097` (duty 2026-08-24→08-30, already has an
open swap request posted for it — verified via `swap_requests` table). Clicking "בקש החלפה"
on that same duty in the "התורנויות שלי" list produces **zero feedback** — no modal, no
toast, no disabled state, no tooltip. `document.querySelectorAll('[role="dialog"]').length`
stayed `0` after the click.
**Impact:** a soldier trying to re-open or edit their swap request will think the button (or
the app) is broken. Anyone who already has an open request for a duty and clicks the same
button they used the first time hits this.
**Fix:** either disable the button with a tooltip ("כבר קיימת בקשה פתוחה לתורנות זו") when an
open request exists for that assignment, or route the click to the existing request's manage
view.

### 1.3 A soldier's own un-claimed swap posting shows approve/reject controls
**Confirmed live + DB-verified:** soldier `1000097`'s open swap request
(`40514ca2-e500-47a7-a21d-4636962f3025`) has **zero rows** in `swap_candidates` — nobody has
offered to cover it. Yet the card in "הבקשות שלי" renders "אשר" / "דחה" buttons plus a
"הערה" (note) textbox right next to "נהל" (manage) and "בטל" (cancel) — controls that read
as manager-approval UI, with nothing behind them to approve. Clicking "אשר" produced no
visible change (tested after ruling out a session artifact via full page reload).
**Impact:** every soldier who posts an open swap and checks back before anyone claims it sees
confusing, seemingly-broken controls.
**Fix:** only render אשר/דחה once a candidate has actually offered (`swap_candidates` has a
row); otherwise show a plain status like "ממתין למציע" (waiting for someone to offer).

### 1.4 Duplicate blank option in the ranges status filter
**File:** `frontend/src/pages/RangesPage.tsx:148` — literally
`<option value="">כל הסטטוסים</option><option value="">כל הסטטוסים</option>` (copy-paste).
Every duty manager who opens the ranges status filter sees the same "כל הסטטוסים" entry
twice.
**Fix:** delete the duplicate line.

### 1.5 Two swap error codes fall through to a generic "שגיאה"
**File:** `frontend/src/utils/translateApiError.ts:42-45` + `frontend/src/i18n/he.json` —
`no_soldier_for_side` and `candidate_mismatch` (raised in
`backend/app/services/swaps.py:875,637`) have no `errors.*` translation entry, unlike the
other ~25 swap error codes. Edge case, but when it fires the user/manager gets no useful
message at all.
**Fix:** add the two missing `errors.*` keys to `he.json`.

### 1.6 README demo-account table is stale and actively misleads onboarding
**File:** `docs/onboarding/user-guide.md:280-300` (and `README.md`) lists soldier PNs
`4000001`–`6000008` and duty-manager PN `2000001`. Actual seeded data (confirmed via DB
query against the running dev DB) has soldiers starting at `1000003`, duty managers at
`2500001`/`2500002`, and `2000001`/`2000002` are actually **commanders**. This cost real time
during this audit — several login attempts failed against the documented PNs before the
actual ones were found by querying the DB directly.
**Fix:** either hardcode a handful of real fixed demo PNs in `seed.py` (simplest, and makes
the docs reliably accurate), or regenerate the table from a `seed --print-accounts` flag.

### 1.7 README roadmap undersells a feature that's already built
**File:** `README.md:309-312` — "Next" lists "notifications (SMS/push) for swap offers and
approval decisions" as not-yet-done. In reality there's a full in-app + email notification
system already live: 53 `NotificationType` values (`backend/app/db/models.py:1211-1263`),
all with real trigger call sites, plus a per-user preferences UI
(`frontend/src/pages/ProfilePage` — the ~40-item checklist under "העדפות התראות"). Only SMS
/push channels are actually missing.
**Fix:** update the roadmap line to reflect what's live (in-app + email notifications ✅) vs.
what's actually still open (SMS/push channels only).

---

## Tier 2 — Real polish, moderate effort

### 2.1 Swap and range actions use native `alert()`/`confirm()`/`prompt()`
**Files:** `frontend/src/pages/SwapsPage.tsx:257-280` (cancel/approve/reject),
`frontend/src/components/OfferSwapModal.tsx:308` (cover-eligibility rejection),
`frontend/src/pages/RangesPage.tsx:73-74,108-110` (bulk delete/clear). These break out of
the app's own styled inline-error/dialog pattern used everywhere else (e.g.
`RangeCancelDialog`, `RangeBulkCancelDialog` sit right next to the `RangesPage` offenders).
Native `prompt()` for a cleanup reason has no character limit and no RTL-aware layout.
**Impact:** every soldier who hits a swap error, and every duty manager doing bulk range
cleanup.
**Fix:** replace with the app's existing modal/toast components — `RangesPage.tsx` already
has the pattern to copy from its own single-cancel flow.

### 2.2 Approval status is a matrix, not a sentence
**Files:** `backend/app/routes/swaps.py:60-84` (`SwapOut`),
`frontend/src/components/SwapApprovalColumns.tsx`, `DirectCommanderApproval.tsx`. Approval
state is exposed as `requester_manager_approvals` / per-candidate `manager_approvals` arrays
and rendered as a 2×2 grid of chips (commander/duty-manager × requester/covering side). There
is no plain-language "ממתין לאישור אחראי התורנויות של המבקש" summary for the common case —
the user has to visually parse the grid to know whose turn it is. This is the direct cause of
finding 1.3 above feeling confusing.
**Fix:** add one summarizing status line derived from the same data, keep the detailed grid
as secondary/expandable detail.

### 2.3 "Your approval is required" notification fires after the approval already happened
**File:** `backend/app/services/swaps.py:979,1215` (`take_free`, `claim_request`) — both set
`requester_side_approved = True` immediately ("asking already implied consent"), then send a
notification to the covering soldier titled "נדרש אישורך" (`:1155`). The wording implies
theirs is one of several approvals still pending, when it's actually the only one left.
**Fix:** reword the notification, or reframe the UI copy to say what's actually still
outstanding.

### 2.4 No pagination on any approvals list
**Files:** `frontend/src/api/constraints.ts:36-38`, `exemptions.ts:103-105`,
`swaps.ts:117-119` — all call unbounded `/pending` endpoints and `ApprovalsPage.tsx` renders
the full result with plain `.map()`. `NotificationsPage.tsx:20` already uses
`usePagePagination` elsewhere in the app, so the pattern exists — it's just not applied here.
**Fix:** apply the existing pagination hook to the three approval lists.

### 2.5 Notification inbox has no sidebar entry
**File:** `frontend/src/pages/NotificationsPage.tsx` is only reachable via the bell
dropdown's "צפה בהכל" link or header search — absent from `UnifiedNav.tsx`'s tab list. A user
who closes the bell without clicking through loses any way back to notification history short
of reopening the bell.
**Fix:** add a nav entry (or at minimum keep the bell's unread badge sticky/discoverable).

### 2.6 Bell dropdown doesn't live-update while open
**File:** `frontend/src/components/NotificationBell.tsx:21-37` — the unread-count poll (30s
interval) and the open-list fetch (`useEffect([open])`, fires once per open) are independent.
A notification arriving while the dropdown is open updates the badge number but not the
visible list until close/reopen.
**Fix:** either share one refresh trigger, or re-fetch the list on the same interval while
`open` is true.

### 2.7 Range candidate exclusion is invisible in the assignment modal
**Files:** `backend/app/services/range_auto_assign.py:257-263` (weapon-exempt /
structurally-ineligible / already-booked soldiers are silently dropped from
`_bulk_eligibility`'s output, by design), `frontend/src/components/ranges/
RangeEditAssignmentsModal.tsx:428-478` (`CandidateTable` has no "excluded soldiers, and why"
affordance). The only place the reason is visible is the separate "כשירות" tab
(`RangesPage.tsx:135`), which means a duty manager has to already suspect a soldier is
excluded and go check a different screen to confirm it.
**Fix:** surface a collapsed "X חיילים לא הוצגו — הצג סיבה" row inside the assignment modal
itself.

### 2.8 Three different Hebrew names for the same "open swap board" concept
**File:** `frontend/src/i18n/he.json:900` (`"board": "לוח מחליפים"`), `:928`
(`"tab_board": "מרקטפלייס"` — the actual tab label), `:574,996`
(`"...שוק ההחלפות"` — the re-publish error message). A soldier who reads the error text
carefully will hit a third, previously-unseen name for the same feature. This is on top of
the already-known README gap that the docs call it "לוח מחליפים" while the UI tab says
"מרקטפלייס".
**Fix:** pick one term (suggest keeping "מרקטפלייס" since that's the live tab label users
already see) and make `he.json` consistent, then update docs to match.

---

## Tier 3 — Needs a product decision or bigger effort

### 3.1 No bulk-approve on the Approvals page
`ApprovalsPage.tsx` (1027 lines, 6 tabs) has only per-row approve/reject — a commander
clearing 20 routine constraint requests after a weekend clicks "אשר" 20 times individually.
Worth doing, but needs a decision on whether bulk-approve should be allowed for all
categories or just constraints (exemptions/swaps arguably need per-row eyes-on given they
affect duty coverage directly).

### 3.2 Rejection-reason requirement is inconsistent across approval types
Constraint rejection is gated client-side (`ApprovalsPage.tsx:550`,
`disabled={!rejectNotes[c.id]}`) — a note is mandatory. Swap manager-rejection
(`backend/app/routes/swaps.py:103-105`, `decision_note`) is fully optional both server- and
client-side. This needs a product decision — should all rejections require a reason
(consistent, more audit-friendly) or is optional-for-swaps intentional? Whichever way it's
decided, the two flows should match.

### 3.3 `RangesPage.tsx` hardcodes all its Hebrew copy instead of using `he.json`
Every other page (`SwapsPage.tsx`, `ApprovalsPage.tsx`, etc.) routes strings through
`t("...")`. `RangesPage.tsx` doesn't — which is the direct root cause of finding 1.4 (a
copy-paste duplicate was invisible because there's no single source of truth to diff against)
and makes any future "מטווח" terminology fix a grep-and-replace across component files
instead of a one-line JSON edit. Worth a dedicated migration pass, not a quick fix.

### 3.4 README's own already-known gaps (not re-litigated here, just tracked)
Per `README.md:326-329`: the open swap board ranks by duty date only (no hierarchy-distance
/ match-quality ranking yet), and the swap-create UI reportedly asks for a raw assignment ID
rather than a duty-day picker. These weren't independently re-verified in this pass (time
budget went to the findings above) — recommend confirming still-current before prioritizing,
since some other "known gap"-shaped assumptions from the docs turned out to be stale (see 1.6,
1.7).

### 3.5 Persistent unresolvable-feeling warning banners
**Confirmed live:** every persona tested (admin, two different soldiers) sees
"⚠️ תאריך מטווחים לא מעודכן" and "⚠️ תאריך אל"ל לא מעודכן" banners on the home screen. They
have a close (✕) but no link/CTA — the soldier profile page does have "שלח בקשת עדכון"
fields for exactly these two dates, but the banner doesn't point there, so the connection
between "here's a warning" and "here's how to fix it" isn't obvious. Low urgency, but touches
every user on every session. Consider either linking the banner text to the profile field, or
suppressing it once a soldier has an active update-request pending for that field.

---

## Suggested next step

Pick which tier(s) to act on. Tier 1 is small enough to implement in one pass (probably 1
subagent session, no product discussion needed). Tier 2 is normal polish work. Tier 3 items
3.1 and 3.2 need a quick product call before anyone writes code — worth 10 minutes of
discussion, not a spec doc.

Once a tier/subset is chosen, this doc's findings should be turned into a proper
task-by-task implementation plan (via `superpowers:writing-plans`) before execution, since
this document intentionally stopped at "what's wrong and why" rather than prescribing
step-by-step code changes.
