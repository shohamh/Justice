# 2026-07-24 — Usability audit findings

Audit of soldier-facing flows (home, profile, my-requests, my-duties, swaps,
notifications, unit calendar, transparency) plus a lighter pass on
approvals/command-dashboard. All findings reproduced live in the browser
against the local dev stack unless noted otherwise.

## Findings (ranked by severity)

### 1. Broken score display on the Transparency/scoreboard table (high visibility)
The "ניקוד מצטבר" (cumulative score) column renders raw un-rounded values like
`28.08000000000000000000000004` instead of a formatted number — visible to
every user on the app's flagship fairness feature.

- Root cause: [frontend/src/pages/TransparencyPage.tsx:583](../../../frontend/src/pages/TransparencyPage.tsx#L583)
  renders `r.cumulative_score` directly instead of `Number(...).toFixed(3)`,
  unlike every other score display in the codebase (e.g.
  [DutyHistoryWidget.tsx:54](../../../frontend/src/components/dashboard/DutyHistoryWidget.tsx#L54)).
- Same bug in [ExportPage.tsx:152](../../../frontend/src/pages/planning/ExportPage.tsx#L152).

### 2. Profile field-update submissions fail silently
[ProfilePage.tsx:126-142](../../../frontend/src/pages/ProfilePage.tsx#L126) —
the exact mechanism a soldier is told to use (via the home-page "date not
updated" banners) to fix their record swallows all backend errors with an
empty `catch {}` block (the code even comments "submission failed
silently"). If it fails, the user sees nothing and has no idea whether it
worked.

### 3. Missing translation leaks a raw i18n key
Every user's Profile → notification preferences table shows the literal
string `notifications.type_transfer_request_rejected` instead of Hebrew
text — `he.json` has `type_transfer_request_pending` but never added the
`_rejected` key.

### 4. Invalid date-range requests fail with zero explanation
On My Requests, submitting a constraint/exemption with an end-date before
the start-date just leaves the "שלח בקשה" button silently disabled at 50%
opacity — no error text like "end date must be after start date." A user
unfamiliar with the app just sees an unresponsive button.
[MyRequestsPage.tsx:199](../../../frontend/src/pages/MyRequestsPage.tsx#L199).

### 5. Confusing "cancelled" status on superseded field-updates
Submitting a second update for the same profile field (e.g. re-submitting a
corrected date) auto-cancels the prior pending one server-side
([soldiers.py:297-306](../../../backend/app/services/soldiers.py#L297)) — by
design, to avoid spamming commanders — but the UI shows it in the same red
styling as "rejected," which reads as "my request was rejected" rather than
"superseded by my own newer one."

### 6. Already-logged-in users can land back on the login form
Navigating to `/login` while authenticated (bookmark, back button, stale
link) shows and lets you interact with the login form instead of
redirecting home — no auth-check guard on
[LoginPage.tsx](../../../frontend/src/pages/LoginPage.tsx) or in
[App.tsx:65](../../../frontend/src/App.tsx#L65).

## Lower-confidence / minor

- Test account had 3 separate open swap requests for the identical duty
  window with no "you already have an open request for this" warning when
  opening a new one — possibly pre-existing test data rather than a live
  bug, flagging for awareness.
- Command Dashboard's "upcoming duties" widget dumps every assigned
  soldier's name as one unbroken flat list (40-50+ names) per busy day with
  no grouping — hard to scan for a commander.

## Multi-role approval-flow audit

Full end-to-end pass logging in as distinct real accounts by role: two
soldiers (מארס 1 / מארס 2, same team — used for the shared-approver case),
their team commander (רשצ מארס), the מחקר mador commander (רמד מחקר, granted
duty-manager scope at the מדור level), and the פוקוס branch commander (רען
פוקוס, granted duty-manager scope at the אגף/branch level). Exercised the
full two-step exemption-request chain and the full two-sided swap chain,
including a scenario where the same commander/duty-manager is the approver
for both soldiers.

### 7. CRITICAL — no non-admin duty manager can ever complete the final exemption approval step
A soldier's exemption request correctly reaches `pending_duty_manager`
after the commander step, but the final "אשר (שלב סופי)" action returns
`403 Forbidden` for **every** duty-manager account tried, regardless of
their assigned scope level — tested with a DM scoped at the מדור (group)
level and one scoped at the אגף (branch) level, both rejected. Only the
admin account (which bypasses the scope check entirely) can approve it, in
direct contradiction of the README's stated design that "admin ...
deliberately does *not* run day-to-day duty operations."

**Root cause** — [`backend/app/services/authority.py:15`](../../../backend/app/services/authority.py#L15):
`REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY = "מרכז"` is compared against
`HierarchyLevelType.key` inside `get_level_rank()`
([`hierarchy.py:38-41`](../../../backend/app/services/hierarchy.py#L38)).
But `key` stores the **English machine key** seeded by migration
[`0059_hierarchy_level_types.py`](../../../backend/alembic/versions/0059_hierarchy_level_types.py)
(`corps`/`division`/`unit`/`department`/`branch`/`group`/`team`) — "מרכז" is
only the *label* for the `department` key. Since no row has `key == "מרכז"`,
`get_level_rank` always returns `None`, so `dm_scope_covers_level` always
returns `False`, so `dm_scope_covers_target` always returns `False` for
every duty manager on every real hierarchy. The same bug pattern affects
`COMMANDER_EXEMPTION_MIN_LEVEL_KEY = "מדור"` (used by
`commander_can_grant_commander_exemption`), silently blocking the
commander-escalation eligibility check for any commander below רס"ן rank,
no matter what node they command.

Why `test_authority.py` doesn't catch it: those tests build their own
bespoke `HierarchyLevelType` rows where `key` is set directly to the Hebrew
string (e.g. `_level(session, "מרכז", 2)`), so `key == label` in the test
fixtures and the mismatch never surfaces. It only manifests against the
real English-keyed seed data.

**Fix direction**: compare against the level's `label` (or store the actual
`key` — `"department"`/`"group"` — as the constant, resolved through
whatever level a real deployment maps to "מרכז"/"מדור").

### 8. The Approvals UI shows an enabled action button the current user isn't authorized to use
Because of #7 (and generally, whenever `dm_scope_covers_target` says no),
the approvals card still renders a clickable "אשר (שלב סופי)" button for
any commander/duty-manager account, rather than disabling/hiding it based
on the same authorization check the backend runs. Clicking produces a
generic toast ("אין הרשאה לבצע פעולה זו" / "שגיאה בביצוע הפעולה") instead of
an explanation. The card *does* have the information needed to do this
right — it already displays "ממתין לאישור קצין אג"ם/מרכז ומעלה" as the
required level — the frontend just doesn't use it to gate the button.

### 9. "Nearest duty manager" hint can point at someone who can never approve
The exemption card's "אחראי תורנויות: רמד מחקר" hint is computed by
`nearest_duty_manager_for_soldier` (nearest DutyManagerScope by hierarchy
distance, no level-rank filter), so — especially combined with #7 — it can
name a duty manager who is *not* actually eligible to complete the
approval, misleading whoever's looking at the queue about who's expected to
act.

### 10. Confirmed working: swap approval with a shared commander/duty-manager
As a positive control, the same test tried the swap flow with מארס 1
(requester) and מארס 2 (coverer) — same team, same team commander (רשצ
מארס), same מדור-level duty manager (רמד מחקר). The approvals roster
correctly renders two distinct rows (requester-side / covering-side) even
though it's the same person for both, and a single "אשר" click resolves
both rows at once (per the `_qualifying_rows_for_actor` design in
[`swaps.py:319`](../../../backend/app/services/swaps.py#L319)). The swap
fully finalized end-to-end: the duty disappeared from מארס 1's swappable
list and now shows status "בוצע" (done). Swaps are **not** affected by the
#7 bug because `duty_manager_chain_for_soldier`
([`approval_scope.py:49`](../../../backend/app/services/approval_scope.py#L49))
has no minimum-level gate — it only checks scope coverage, not level rank.
