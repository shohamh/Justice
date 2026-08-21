# UX Audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the usability papercuts found in
[2026-08-21-ux-audit-findings-and-fixes.md](2026-08-21-ux-audit-findings-and-fixes.md), per
the human's decisions below.

**Architecture:** No architectural change. This is a series of independent, narrowly-scoped
fixes across `frontend/src/{pages,components,i18n,utils}` and
`backend/app/{routes,services,scripts}`. Each task is self-contained and can be implemented
and reviewed in isolation — there is no required ordering between tasks except where a task
explicitly says it depends on another.

**Tech Stack:** React + TypeScript + Vite (frontend), FastAPI + SQLAlchemy (backend), Hebrew
i18n via `frontend/src/i18n/he.json` + `react-i18next`.

## Decisions from the human (scope for this round)

- **Keep the 2×2 approval-status grid as-is.** The original audit's finding 2.2 ("replace the
  grid with a plain-language summary line") is **dropped**. Do not touch
  `SwapApprovalColumns.tsx` / `DirectCommanderApproval.tsx` rendering.
- **Skip bulk-approve** (original finding 3.1) — not in scope for this round.
- **Skip the rejection-reason consistency change** (original finding 3.2) — the human
  confirmed swaps should *not* require a reason to reject; constraints stay as they are today.
  No code change needed; this finding is closed as "working as intended."

## Corrections from re-verification

Two findings from the original audit did **not** reproduce under closer, code-level
verification and are **dropped from this plan** (do not implement fixes for them):

- **Original 1.2 ("בקש החלפה silently does nothing")** — false. Live re-test: the create-swap
  modal (`AskSwapModal.tsx`) opens correctly, its Save button is correctly disabled until a
  target or the marketplace checkbox is picked (`disabled={enrollmentPending ||
  nothingSelected}`, `AskSwapModal.tsx:200`), and submitting against a duty that already has
  an open request surfaces a clear inline error: "כבר קיימת בקשה ממתינה". The original negative
  result was a browser-automation artifact (a stale click landed on nothing), not a product
  bug.
- **Original 2.3 ("take_free/claim_request notification wording is misleading")** — false.
  `take_free` (`backend/app/services/swaps.py:1074-1159`) sets
  `requester_side_approved=False` and correctly tells the original assignee their approval is
  required. `claim_request` (`:936-993`) does set it `True` on claim, but its notification to
  the requester just says "הייתה הצעת החלפה" (neutral, doesn't claim approval is needed) — no
  actual mismatch. No code change needed.

**Original 3.5 (warning banners with "no CTA")** is **downgraded, not dropped** — the banner
in `AlertBanners.tsx:108` already navigates to `/profile` on click
(`onClick={() => navigate("/profile")}`, with `cursor-pointer` styling). The real gap is
narrower: it lands on the top of the profile page instead of scrolling to the specific
מטווחים/אל"ל field. Task 15 below fixes that narrower gap.

---

## Global Constraints

- Follow existing patterns: Hebrew UI strings go through `t("...")` / `he.json`, not inline
  literals (except in the one task, #16, whose whole job is fixing that for `RangesPage.tsx`).
- Every touched frontend file must pass `npm run lint` (zero warnings) and `npm run typecheck`.
- Every touched backend file must pass `ruff check`, `ruff format --check`, and `mypy app`.
- Run the relevant existing test suite after each task — `pytest -q` (backend) or
  `npm test` (frontend) — before committing. Don't add new test infra beyond what a task
  explicitly calls for.
- Small, focused commits — one per task, following the repo's existing commit style.

---

## Tier 1 tasks

### Task 1: Include pending swaps in the commander/DM approvals badge count

**Files:**
- Create: `frontend/src/utils/swapApprovals.ts`
- Modify: `frontend/src/pages/ApprovalsPage.tsx` (use the extracted helper instead of its
  local copy)
- Modify: `frontend/src/components/UnifiedNav.tsx:102-114` (add swaps to the badge count)
- Test: `frontend/src/utils/swapApprovals.test.ts`

**Context:** `UnifiedNav.tsx`'s `pendingCount` (used for both the "פעולות מפקד" nav badge at
line 178 and the "אישור בקשות" badge at line 200) currently sums constraints, exemptions,
field-updates, enrollments, and hakpaza — never swaps. `ApprovalsPage.tsx:224-232` has the
correct "can this user actually act on this swap" logic (`swapIsActionable`,
`canActCommander`, `canActDutyManager`), but it's private to that component. Extract it so
both places share one implementation.

- [ ] **Step 1: Extract the actionable-swap logic into a shared, testable function**

Create `frontend/src/utils/swapApprovals.ts`:

```typescript
import type { SwapRequest, SwapManagerApproval } from "../api/swaps";
import { groupByKind } from "../components/DirectCommanderApproval";

export interface ApprovalActor {
  id: string;
  isAdmin: boolean;
}

function canAct(approvals: SwapManagerApproval[], actor: ApprovalActor): boolean {
  return actor.isAdmin || approvals.some((a) => a.commander_id === actor.id);
}

/** A swap is "actionable" for this actor if they have standing to approve
 * either the requester side or any live candidate's covering side — either
 * as a matching chain commander/duty-manager, or as an admin (who can act on
 * anything). Mirrors the visibility rule the approvals page uses to split
 * "cards I can decide" from "cards I can only watch." */
export function isSwapActionable(swap: SwapRequest, actor: ApprovalActor): boolean {
  const reqGroups = groupByKind(swap.requester_manager_approvals);
  if (canAct(reqGroups.commander, actor) || canAct(reqGroups.duty_manager, actor)) return true;
  const liveCandidates = swap.candidates.filter((c) => c.status === "pending" || c.status === "accepted");
  return liveCandidates.some((candidate) => {
    const covGroups = groupByKind(candidate.manager_approvals);
    return canAct(covGroups.commander, actor) || canAct(covGroups.duty_manager, actor);
  });
}

export function countActionableSwaps(swaps: SwapRequest[], actor: ApprovalActor): number {
  return swaps.filter((s) => isSwapActionable(s, actor)).length;
}
```

- [ ] **Step 2: Write a test for the extracted function**

Create `frontend/src/utils/swapApprovals.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { isSwapActionable, countActionableSwaps } from "./swapApprovals";
import type { SwapRequest } from "../api/swaps";

function approval(commander_id: string, overrides: Partial<SwapRequest["requester_manager_approvals"][number]> = {}) {
  return {
    commander_id, commander_name: null, approved: false, approved_by: null,
    approved_by_name: null, approved_at: null, rejected: false, rejected_by: null,
    rejected_by_name: null, rejected_at: null, approver_kind: "commander" as const,
    ...overrides,
  };
}

function baseSwap(overrides: Partial<SwapRequest> = {}): SwapRequest {
  return {
    id: "s1", duty_assignment_id: "d1", duty_date: "2026-01-01",
    requesting_soldier_id: "req1", open_to_marketplace: false, status: "open",
    reason: null, requester_side_approved: null, decision_note: null,
    created_at: "2026-01-01T00:00:00Z", duty_type_name: null, duty_location_name: null,
    duty_type_id: null, duty_location_id: null, duty_start_date: null, duty_end_date: null,
    duty_shift_id: null, requester_manager_approvals: [], candidates: [],
    ...overrides,
  };
}

describe("isSwapActionable", () => {
  it("is actionable for the matching requester-side commander", () => {
    const swap = baseSwap({ requester_manager_approvals: [approval("cmd1")] });
    expect(isSwapActionable(swap, { id: "cmd1", isAdmin: false })).toBe(true);
  });

  it("is not actionable for an unrelated commander", () => {
    const swap = baseSwap({ requester_manager_approvals: [approval("cmd1")] });
    expect(isSwapActionable(swap, { id: "cmd2", isAdmin: false })).toBe(false);
  });

  it("is actionable for admins regardless of approver list", () => {
    const swap = baseSwap({ requester_manager_approvals: [approval("cmd1")] });
    expect(isSwapActionable(swap, { id: "anyone", isAdmin: true })).toBe(true);
  });

  it("counts only actionable swaps", () => {
    const mine = baseSwap({ id: "s1", requester_manager_approvals: [approval("cmd1")] });
    const notMine = baseSwap({ id: "s2", requester_manager_approvals: [approval("cmd2")] });
    expect(countActionableSwaps([mine, notMine], { id: "cmd1", isAdmin: false })).toBe(1);
  });
});
```

- [ ] **Step 3: Run the new test, verify it passes**

Run: `cd frontend && npx vitest run src/utils/swapApprovals.test.ts`
Expected: 4 passed.

- [ ] **Step 4: Make `ApprovalsPage.tsx` use the shared function instead of its local copy**

In `frontend/src/pages/ApprovalsPage.tsx`, replace the local `canActCommander`,
`canActDutyManager`, and `swapIsActionable` (lines 206-232, the swap-specific parts only —
leave `exemptionIsActionable` and the `isAdmin` const alone) with:

```typescript
import { isSwapActionable } from "../utils/swapApprovals";
// ...
const swapsActionable = swapItems.filter((s) => isSwapActionable(s, { id: user?.id ?? "", isAdmin }));
const swapsWaiting = swapItems.filter((s) => !isSwapActionable(s, { id: user?.id ?? "", isAdmin }));
```

Keep `canActCommander`/`canActDutyManager` if other code on the page (constraint/exemption
rendering) still uses them — check their other call sites before deleting.

- [ ] **Step 5: Add swaps to the `UnifiedNav.tsx` badge aggregation**

In `frontend/src/components/UnifiedNav.tsx`, import `listPendingSwaps` from `../api/swaps`
and `countActionableSwaps` from `../utils/swapApprovals`, then update the effect at
lines 102-114:

```typescript
useEffect(() => {
  if (!canApprove) return;
  void (async () => {
    const [c, e, f, enroll, hk, swaps] = await Promise.all([
      getPendingCount().catch(() => 0),
      getPendingExemptionCount().catch(() => 0),
      getPendingFieldUpdateCount().catch(() => 0),
      listPendingEnrollments().then((r) => r.length).catch(() => 0),
      getPendingHakpazaCount().catch(() => 0),
      listPendingSwaps().catch(() => [] as SwapRequest[]),
    ]);
    const isAdmin = user?.role === "admin";
    const swapCount = user ? countActionableSwaps(swaps, { id: user.id, isAdmin }) : 0;
    setPendingCount(c + e + f + enroll + hk + swapCount);
  })();
}, [canApprove, location.pathname, user]);
```

Import `SwapRequest` type from `../api/swaps` for the catch fallback's type annotation.

- [ ] **Step 6: Manual verification**

Start the dev stack, log in as a duty manager with a pending swap approval waiting (query the
DB for one, same approach as the audit), and confirm the "פעולות מפקד" / "אישור בקשות" badge
count now includes it. Confirm the count still matches `swapsActionable.length` shown on the
Approvals page's swaps tab.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/utils/swapApprovals.ts frontend/src/utils/swapApprovals.test.ts frontend/src/pages/ApprovalsPage.tsx frontend/src/components/UnifiedNav.tsx
git commit -m "fix: include pending swap approvals in the commander/DM approvals badge count"
```

---

### Task 2: Don't show approve/reject controls on a swap request with no offers yet

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx:309`
- Test: manual (this file has no existing unit test harness for `renderMySwapCard`; a
  snapshot/unit test would need scaffolding disproportionate to a one-line condition change)

**Context:** `renderMySwapCard` in `SwapsPage.tsx` already computes `liveCandidates` at
line 289 (`swap.candidates.filter((c) => c.status === "pending" || c.status === "accepted")`)
and uses it to decide whether to show the approval columns (line 290). The approve/reject
block right below it (line 309) doesn't use that same guard — it only checks
`swap.status === "open" && swap.requester_side_approved !== true`, so it renders even when
`liveCandidates.length === 0` (nothing to approve). Confirmed live + via DB query
(`swap_candidates` had zero rows for the open request that showed these controls).

- [ ] **Step 1: Add the missing guard**

In `frontend/src/pages/SwapsPage.tsx`, change line 309 from:

```typescript
      {swap.status === "open" && swap.requester_side_approved !== true && (
```

to:

```typescript
      {swap.status === "open" && swap.requester_side_approved !== true && liveCandidates.length > 0 && (
```

- [ ] **Step 2: Manual verification**

In the dev app, as a soldier with an open swap request that has zero candidates, confirm the
"אשר"/"דחה"/note-field row no longer renders on that card (only "נהל"/"בטל" should show). Then
have another soldier offer to cover it (or claim it via the marketplace) and confirm the
approve/reject row now appears.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/SwapsPage.tsx
git commit -m "fix: hide swap approve/reject controls until a candidate has actually offered"
```

---

### Task 3: Remove the duplicate blank option in the ranges status filter

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx:148`

**Context:** The status `<select>` has `<option value="">כל הסטטוסים</option>` twice in a
row (copy-paste artifact).

- [ ] **Step 1: Delete the duplicate**

In `frontend/src/pages/RangesPage.tsx` line 148, find:
```
<option value="">כל הסטטוסים</option><option value="">כל הסטטוסים</option>
```
and delete one of the two identical `<option>` tags, leaving just one.

- [ ] **Step 2: Manual verification**

Open the ranges page status filter dropdown, confirm "כל הסטטוסים" now appears once.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/RangesPage.tsx
git commit -m "fix: remove duplicate blank option in ranges status filter"
```

*(If Task 16 — the RangesPage i18n migration — is done in the same pass, fold this fix into
that task instead of committing it separately, since Task 16 rewrites this same line.)*

---

### Task 4: Translate the two missing swap error codes

**Files:**
- Modify: `frontend/src/i18n/he.json`

**Context:** `translateApiError` (`frontend/src/utils/translateApiError.ts:42-45`) looks up
`errors.<code>` and falls back to a generic message when the key is missing. Backend codes
`no_soldier_for_side` (`backend/app/services/swaps.py:875`) and `candidate_mismatch`
(`backend/app/services/swaps.py:637`) have no matching key today (confirmed via grep — zero
matches in `he.json`), unlike every other swap error code.

- [ ] **Step 1: Read the two raise sites to write an accurate message**

Read `backend/app/services/swaps.py` around lines 637 and 875 to confirm what triggers each
(a mismatched candidate id across concurrent requests, and a missing soldier record for one
side of a swap) so the Hebrew message is accurate, not generic filler.

- [ ] **Step 2: Add the two keys under the existing `errors` namespace**

In `frontend/src/i18n/he.json`, in the `errors` object (same namespace as
`already_on_marketplace` at line 574), add:

```json
    "no_soldier_for_side": "לא נמצא חייל מתאים לצד זה של הבקשה",
    "candidate_mismatch": "הבקשה השתנתה בינתיים על ידי מישהו אחר — רענן ונסה שוב",
```

Adjust wording after reading the raise sites in Step 1 if the circumstances are more specific
than this.

- [ ] **Step 3: Manual verification**

Run `npm run typecheck` and `npm run lint` in `frontend/` to confirm valid JSON and no unused
key lint (if the repo lints i18n key usage). Optionally trigger the race condition in a test
environment to see the new message rendered instead of "שגיאה".

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "fix: add missing Hebrew translations for two swap error codes"
```

---

### Task 5: Fix stale demo-account documentation by printing real accounts from the seed script

**Files:**
- Modify: `backend/app/scripts/seed.py` (around line 1836, the end-of-seed summary block)
- Modify: `docs/onboarding/user-guide.md:280-300`

**Context:** The documented demo PNs (`4000001`-`6000008`, duty-manager `2000001`) don't
match what `seed.py` actually generates — soldier PNs and role-to-PN mapping depend on
generation order and drift whenever the hierarchy/soldier-creation code changes. Rather than
hardcoding numbers in the docs (which will go stale again), have the seed script print one
example login per role at the end of a real run — self-updating documentation.

- [ ] **Step 1: Find one soldier per role to print**

In `backend/app/scripts/seed.py`, the `all_soldiers` list (referenced at line 1808 —
`f"  {len(all_soldiers)} soldiers"`) already holds every created `Soldier` object with `.role`
and `.personal_number`. Add a helper right before the final `_safe_print` block (before
line 1806):

```python
        def _example(role: str) -> str:
            match = next((s for s in all_soldiers if s.role == role), None)
            return match.personal_number if match else "—"
```

- [ ] **Step 2: Print example login credentials in the summary**

After the existing `_safe_print(f"  {fu_count} profile field update requests")` line (the
last line of the summary block, currently line 1836), add:

```python
        _safe_print("")
        _safe_print("Demo logins (password 1234567890 for all):")
        _safe_print(f"  admin: {_example('admin')}")
        _safe_print(f"  duty_manager: {_example('duty_manager')}")
        _safe_print(f"  commander: {_example('commander')}")
        _safe_print(f"  soldier: {_example('soldier')}")
```

- [ ] **Step 3: Run the seed script and confirm the output**

Run: `cd backend && uv run python -m app.scripts.seed --force`
Expected: the summary block ends with the four demo login lines showing real, currently-valid
personal numbers.

- [ ] **Step 4: Update the docs to point at this instead of a static table**

In `docs/onboarding/user-guide.md`, replace the static PN table (lines ~286-295) with:

```markdown
Personal numbers are assigned during seeding and can shift as the seed script evolves — the
seed script itself prints one example login per role at the end of a run
(`uv run python -m app.scripts.seed`), under "Demo logins". Use those exact values; don't
rely on any specific personal number written down here going stale.
```

Keep the admin's PN `1000001` mentioned as-is if you want one always-true example — it's
created deterministically by `bootstrap.py`/`seed.py`'s special-cased admin block
(`seed.py:294-317`) and won't drift.

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/seed.py docs/onboarding/user-guide.md
git commit -m "fix: print real demo account logins from seed.py instead of a stale doc table"
```

---

### Task 6: Fix the README roadmap to reflect that notifications are already built

**Files:**
- Modify: `README.md:309-312`

**Context:** The "Next" roadmap section lists "notifications (SMS/push) for swap offers and
approval decisions" as not-yet-done. A full in-app + email notification system already
exists: 53 `NotificationType` values (`backend/app/db/models.py:1211-1263`), all with live
trigger call sites, plus a per-user preferences UI. Only SMS/push channels are genuinely
missing.

- [ ] **Step 1: Update the roadmap line**

In `README.md`, in the "Next" bullet list (around line 311), change:

```markdown
notifications (SMS/push) for swap offers and approval decisions;
```

to:

```markdown
SMS/push notification channels (in-app + email notifications already ship — 50+ event types,
per-user preferences);
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: correct README roadmap — notifications already ship, only SMS/push is missing"
```

---

## Tier 2 tasks

### Task 7: Replace native `alert()`/`confirm()` in the swap flow with the app's own error pattern

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx:257-280`
- Modify: `frontend/src/components/OfferSwapModal.tsx:305-310`

**Context:** `handleCancel`, `handleSoldierApprove`, `handleSoldierReject`
(`SwapsPage.tsx:257-280`) all use `alert(translateApiError(...))` on failure, while the rest
of the app (including the create/edit flow in `AskSwapModal.tsx`) shows a styled inline error.
`OfferSwapModal.tsx:308` uses `alert(elig?.reason ?? ...)` for an ineligibility message on
mobile tap.

- [ ] **Step 1: Add an inline error-message state to `SwapsPage`**

In `frontend/src/pages/SwapsPage.tsx`, add state near the other swap-related state (around
line 264):

```typescript
const [swapActionError, setSwapActionError] = useState<string | null>(null);
```

- [ ] **Step 2: Replace the three `alert()` calls**

Change lines 257-280 from:

```typescript
  async function handleCancel(id: string) {
    try { await cancelSwap(id); await refreshSwapData(); }
    catch (err: unknown) {
      alert(translateApiError(err, t, "שגיאה"));
    }
  }

  const [swapRejectNote, setSwapRejectNote] = useState<Record<string, string>>({});

  async function handleSoldierApprove(id: string) {
    try { await soldierApproveSwap(id); await refreshSwapData(); }
    catch (err: unknown) {
      alert(translateApiError(err, t, "שגיאה"));
    }
  }
  async function handleSoldierReject(id: string) {
    try {
      await soldierRejectSwap(id, swapRejectNote[id]);
      setSwapRejectNote((prev) => { const next = { ...prev }; delete next[id]; return next; });
      await refreshSwapData();
    } catch (err: unknown) {
      alert(translateApiError(err, t, "שגיאה"));
    }
  }
```

to:

```typescript
  async function handleCancel(id: string) {
    try { await cancelSwap(id); await refreshSwapData(); }
    catch (err: unknown) {
      setSwapActionError(translateApiError(err, t, "שגיאה"));
    }
  }

  const [swapRejectNote, setSwapRejectNote] = useState<Record<string, string>>({});

  async function handleSoldierApprove(id: string) {
    try { await soldierApproveSwap(id); await refreshSwapData(); }
    catch (err: unknown) {
      setSwapActionError(translateApiError(err, t, "שגיאה"));
    }
  }
  async function handleSoldierReject(id: string) {
    try {
      await soldierRejectSwap(id, swapRejectNote[id]);
      setSwapRejectNote((prev) => { const next = { ...prev }; delete next[id]; return next; });
      await refreshSwapData();
    } catch (err: unknown) {
      setSwapActionError(translateApiError(err, t, "שגיאה"));
    }
  }
```

- [ ] **Step 3: Render the error near the existing `loadError` banner**

Find the existing `{loadError && (<p className="text-red-500 text-sm mb-3">{loadError}</p>)}`
block (around line 462-464) and add an equivalent block right after it:

```typescript
        {swapActionError && (
          <p className="text-red-500 text-sm mb-3" role="alert" data-testid="swap-action-error">
            {swapActionError}
            <button type="button" onClick={() => setSwapActionError(null)} className="mr-2 underline">
              {t("common.dismiss", { defaultValue: "סגור" })}
            </button>
          </p>
        )}
```

Also clear `swapActionError` at the top of `refreshSwapData` (so a subsequent successful
action clears a stale error) — add `setSwapActionError(null);` as the first line of the
function.

- [ ] **Step 4: Fix `OfferSwapModal.tsx`'s mobile-tap alert**

In `frontend/src/components/OfferSwapModal.tsx`, this component already has an `error` state
pattern (used elsewhere in the same file per the existing convention — check around
line 111-113 for the exact state name/setter before editing). Replace:

```typescript
                    onClick={(e) => {
                      if (isIneligible && isMobile) {
                        e.preventDefault();
                        alert(elig?.reason ?? "חייל זה אינו יכול לקבל תורנות זו");
                      }
                    }}
```

with a call to that same error setter instead of `alert(...)`, e.g.:

```typescript
                    onClick={(e) => {
                      if (isIneligible && isMobile) {
                        e.preventDefault();
                        setError(elig?.reason ?? "חייל זה אינו יכול לקבל תורנות זו");
                      }
                    }}
```

(Use whatever the file's existing error-state setter is actually named — read the file first;
don't introduce a second, parallel error state if one already exists.)

- [ ] **Step 5: Manual verification**

Trigger a swap cancel/approve/reject failure (e.g. cancel a swap twice in two tabs to hit a
race) and confirm a styled inline message appears instead of a browser `alert()` dialog. Tap
an ineligible target on a narrow/mobile viewport in the offer modal and confirm the same.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SwapsPage.tsx frontend/src/components/OfferSwapModal.tsx
git commit -m "fix: replace native alert() with inline errors in the swap flow"
```

---

### Task 8: Replace native `confirm()`/`prompt()`/`alert()` in the ranges bulk actions

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Create: `frontend/src/components/ranges/ConfirmDialog.tsx` (reusable styled
  confirm/reason dialog)

**Depends on:** none — can be done independently of Task 16 (the i18n migration), but if both
are being done, do this one first since Task 16 will move the strings this task touches into
`he.json` anyway.

**Context:** `bulkDelete` (`RangesPage.tsx:71-86`), `bulkClear` (`:102-119`), and the
single-event delete handler inline in the row actions (`:148`) use `confirm()`/`prompt()`/
`alert()`, while the adjacent cancel flow already has a proper styled dialog
(`RangeCancelDialog`, `RangeBulkCancelDialog`). Build one reusable dialog and use it for all
three.

- [ ] **Step 1: Look at `RangeCancelDialog.tsx` for the existing styling pattern**

Read `frontend/src/components/ranges/RangeCancelDialog.tsx` fully before writing the new
component, so `ConfirmDialog` matches its visual conventions (modal backdrop, RTL layout,
button styling).

- [ ] **Step 2: Create a generic reusable confirm dialog**

Create `frontend/src/components/ranges/ConfirmDialog.tsx`:

```typescript
import { useState } from "react";

interface Props {
  open: boolean;
  title: string;
  message: string;
  /** When set, shows a required free-text reason field (used for the "clear
   * assignments" action, replacing window.prompt()). */
  reasonLabel?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: (reason?: string) => void;
  onClose: () => void;
}

export default function ConfirmDialog({
  open, title, message, reasonLabel, confirmLabel = "אישור", cancelLabel = "ביטול",
  danger = false, onConfirm, onClose,
}: Props) {
  const [reason, setReason] = useState("");
  if (!open) return null;
  const needsReason = reasonLabel !== undefined;
  const canConfirm = !needsReason || reason.trim().length > 0;
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" dir="rtl" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-5 w-full max-w-sm space-y-3" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold dark:text-gray-100">{title}</h2>
        <p className="text-sm text-gray-600 dark:text-gray-300">{message}</p>
        {needsReason && (
          <div>
            <label className="block text-sm font-medium dark:text-gray-100 mb-1">{reasonLabel}</label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              rows={3}
              maxLength={500}
            />
          </div>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="px-3 py-1.5 text-sm rounded border dark:border-gray-600 dark:text-gray-100">
            {cancelLabel}
          </button>
          <button
            type="button"
            disabled={!canConfirm}
            onClick={() => onConfirm(needsReason ? reason.trim() : undefined)}
            className={`px-3 py-1.5 text-sm rounded text-white disabled:opacity-40 ${danger ? "bg-red-600 hover:bg-red-700" : "bg-indigo-600 hover:bg-indigo-700"}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Wire it into `bulkDelete`**

In `RangesPage.tsx`, add state:

```typescript
const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);
```

Change `bulkDelete` (lines 71-86) to stop calling `confirm()` and instead be invoked after the
dialog confirms:

```typescript
  const deletableCount = selectedEvents.filter(e => count(e, false) === 0 && count(e, true) === 0).length;
  async function bulkDelete() {
    const deletable = selectedEvents.filter(e => count(e, false) === 0 && count(e, true) === 0);
    setBulkBusy(true);
    setBulkError("");
    try {
      await Promise.allSettled(deletable.map(e => deleteRangeEvent(e.id)));
      setSelectedIds(new Set());
      await invalidate();
    } catch {
      setBulkError("מחיקת המטווחים נכשלה");
    } finally {
      setBulkBusy(false);
      setBulkDeleteConfirmOpen(false);
    }
  }
```

Change the "מחק מטווחים" button's `onClick` (line 144) from `() => void bulkDelete()` to a
handler that first checks whether there's anything deletable (replacing the old
`alert("כל המטווחים...")` early-return) and otherwise opens the dialog:

```typescript
onClick={() => { if (deletableCount === 0) { setBulkError("כל המטווחים הנבחרים מכילים שיבוצים ולא ניתן למחוק אותם."); return; } setBulkDeleteConfirmOpen(true); }}
```

Add the dialog near the other range dialogs (next to `RangeCancelDialog`/
`RangeBulkCancelDialog` at the bottom of the JSX, around line 152):

```typescript
<ConfirmDialog
  open={bulkDeleteConfirmOpen}
  title="מחיקת מטווחים"
  message={`למחוק ${deletableCount} מטווחים לצמיתות?`}
  danger
  confirmLabel="מחק"
  onConfirm={() => void bulkDelete()}
  onClose={() => setBulkDeleteConfirmOpen(false)}
/>
```

- [ ] **Step 4: Wire it into `bulkClear`**

Add state:

```typescript
const [bulkClearConfirmOpen, setBulkClearConfirmOpen] = useState(false);
```

Change `bulkClear` (lines 102-119) to drop the `confirm()`/`window.prompt()` calls and take
the reason as a parameter instead:

```typescript
  async function bulkClear(reason: string) {
    setBulkBusy(true);
    setBulkError("");
    try {
      const details = await Promise.all(selectedEvents.map(e => getRangeEvent(e.id)));
      await Promise.all(details.flatMap(e => e.assignments.map(a => removeRangeAssignment(e.id, a.id, reason))));
      setSelectedIds(new Set());
      await invalidate();
    } catch {
      setBulkError("ניקוי השיבוצים נכשל");
    } finally {
      setBulkBusy(false);
      setBulkClearConfirmOpen(false);
    }
  }
```

Change the "נקה שיבוצים" button's `onClick` (line 142) to `() => setBulkClearConfirmOpen(true)`,
and add:

```typescript
<ConfirmDialog
  open={bulkClearConfirmOpen}
  title="ניקוי שיבוצים"
  message={`לנקות שיבוצים מ-${selectedEvents.length} מטווחים?`}
  reasonLabel="סיבת הניקוי (תחול על כל השיבוצים שינוקו)"
  confirmLabel="נקה"
  danger
  onConfirm={(reason) => void bulkClear(reason ?? "")}
  onClose={() => setBulkClearConfirmOpen(false)}
/>
```

- [ ] **Step 5: Wire it into the single-event delete confirm**

In the row-actions JSX (the big line ~148 block), find:

```typescript
onClick={async () => { if (!confirm("למחוק?")) return; setSelected(current => current === e.id ? null : current); await deleteRangeEvent(e.id); await invalidate(); }}
```

Replace with a state-driven equivalent: add `const [deleteConfirmId, setDeleteConfirmId] =
useState<string | null>(null);`, change the button's `onClick` to
`() => setDeleteConfirmId(e.id)`, and add one more `ConfirmDialog` near the others:

```typescript
<ConfirmDialog
  open={!!deleteConfirmId}
  title="מחיקת מטווח"
  message="למחוק מטווח זה?"
  danger
  confirmLabel="מחק"
  onConfirm={async () => {
    if (!deleteConfirmId) return;
    setSelected(current => current === deleteConfirmId ? null : current);
    await deleteRangeEvent(deleteConfirmId);
    await invalidate();
    setDeleteConfirmId(null);
  }}
  onClose={() => setDeleteConfirmId(null)}
/>
```

- [ ] **Step 6: Manual verification**

In the dev app as a duty manager, select several ranges and try "נקה שיבוצים", "בטל מטווחים",
"מחק מטווחים", and the single-row delete — confirm all show the app's own styled dialog, none
trigger a native browser popup, and the reason field for "נקה שיבוצים" is required before the
confirm button enables.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/RangesPage.tsx frontend/src/components/ranges/ConfirmDialog.tsx
git commit -m "fix: replace native confirm()/prompt()/alert() in ranges bulk actions with styled dialogs"
```

---

### Task 9: Client-side pagination for the three approvals lists

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`

**Context:** `ApprovalsPage.tsx` fetches unbounded `/constraints/pending`,
`/exemption-requests/pending`, `/swaps/pending` lists (no backend offset/limit support exists
for these endpoints) and renders every row via plain `.map()`. Given the pilot's scale
(~100 soldiers per the README), full server-side pagination is more than this needs — slice
the already-fetched arrays client-side using the existing `usePagePagination` hook (already
used by `NotificationsPage.tsx`), with one independent page param per tab so switching tabs
doesn't reset another tab's page.

- [ ] **Step 1: Add three independent pagination instances**

In `frontend/src/pages/ApprovalsPage.tsx`, import `usePagePagination` from
`../hooks/usePagePagination` and add, near the other list-derived consts:

```typescript
const CONSTRAINTS_PAGE_SIZE = 20;
const constraintsPaging = usePagePagination({ limit: CONSTRAINTS_PAGE_SIZE, paramName: "cpage" });
const exemptionsPaging = usePagePagination({ limit: CONSTRAINTS_PAGE_SIZE, paramName: "epage" });
const swapsPaging = usePagePagination({ limit: CONSTRAINTS_PAGE_SIZE, paramName: "spage" });
```

- [ ] **Step 2: Slice each rendered list and add pager controls**

For each of the three lists that currently render via `.map()` unbounded (the constraints tab
around where `items`/`total` is used, `erActionable`, and `swapsActionable` at line 711),
slice before rendering, e.g. for swaps:

```typescript
const swapsPageItems = swapsActionable.slice(swapsPaging.offset, swapsPaging.offset + swapsPaging.limit);
```

and render `swapsPageItems.map(...)` instead of `swapsActionable.map(...)` at line 711. Add a
small pager below each list (reuse whatever pager UI `NotificationsPage.tsx` already has —
read it first and copy its pattern rather than inventing a new one), e.g.:

```typescript
{swapsActionable.length > CONSTRAINTS_PAGE_SIZE && (
  <div className="flex justify-center gap-2 pt-2 text-sm">
    <button type="button" disabled={swapsPaging.page <= 1} onClick={() => swapsPaging.setPage(swapsPaging.page - 1)} className="px-2 py-1 border rounded disabled:opacity-40 dark:border-gray-600">הקודם</button>
    <span className="text-gray-500">{swapsPaging.page} / {Math.ceil(swapsActionable.length / CONSTRAINTS_PAGE_SIZE)}</span>
    <button type="button" disabled={swapsPaging.offset + swapsPaging.limit >= swapsActionable.length} onClick={() => swapsPaging.setPage(swapsPaging.page + 1)} className="px-2 py-1 border rounded disabled:opacity-40 dark:border-gray-600">הבא</button>
  </div>
)}
```

Repeat the same slice-and-pager pattern for the constraints list (`items`) and the exemptions
list (`erActionable`). Leave `waiting`/read-only sections and the other tabs (field updates,
enrollment, transfers) as-is — this task's scope is the three lists the original audit named.

- [ ] **Step 3: Manual verification**

Seed or manually create more than 20 pending constraint requests in one commander's scope,
open Approvals, confirm only 20 render with a working pager, and confirm the tab's count
badge (which uses the full unsliced array, not the page) doesn't change.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx
git commit -m "fix: paginate the constraints/exemptions/swaps approval lists"
```

---

### Task 10: Add a sidebar nav entry for the notification inbox

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx`
- Modify: `frontend/src/i18n/he.json` (add `nav.notifications` if not already present — check
  first)

**Context:** `/notifications` (`NotificationsPage.tsx`) is only reachable via the bell
dropdown's "צפה בהכל" link or header search — it has no entry in `UnifiedNav.tsx`'s
`baseTabs` (confirmed via grep — no `nav.notifications` or `/notifications` reference in that
file).

- [ ] **Step 1: Check whether an icon/key convention already fits**

Check `he.json` for an existing `nav.notifications` key (search for it) — if missing, add one
near the other `nav.*` keys with value `"התראות"`.

- [ ] **Step 2: Add the tab**

In `frontend/src/components/UnifiedNav.tsx`, add a new entry to `baseTabs` (around line 164),
using the `Bell` icon from `lucide-react` (already a dependency — see other icon imports at
the top of the file):

```typescript
{ label: t("nav.notifications"), icon: <Bell size={20} />, to: "/notifications", testId: "nav-notifications" },
```

Place it logically — e.g. right after `nav.swaps` or near `nav.transparency`, whichever reads
better in the sidebar; this is a judgment call, not a strict requirement.

- [ ] **Step 3: Manual verification**

Confirm the new nav item appears for every role (it should — notifications aren't
role-scoped) and routes to `/notifications`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/UnifiedNav.tsx frontend/src/i18n/he.json
git commit -m "fix: add a sidebar nav entry for the notification inbox"
```

---

### Task 11: Make the notification bell's open list live-update

**Files:**
- Modify: `frontend/src/components/NotificationBell.tsx:21-37`

**Context:** The unread-count poll (30s interval, lines 21-31) and the open-list fetch
(`useEffect([open])`, lines 33-37, fires once per open transition) are independent — a
notification arriving while the dropdown is open updates the badge but not the visible list.

- [ ] **Step 1: Merge the two effects so the interval also refreshes the open list**

Replace lines 21-37:

```typescript
  useEffect(() => {
    const fetch = async () => {
      try {
        const { count } = await getUnreadCount();
        setUnread(count);
      } catch { /* ignore */ }
    };
    fetch();
    const interval = setInterval(fetch, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (open) {
      listNotifications({ is_read: false, limit: 5 }).then((r) => setNotifications(r.items)).catch(() => {});
    }
  }, [open]);
```

with:

```typescript
  const openRef = useRef(open);
  useEffect(() => { openRef.current = open; }, [open]);

  useEffect(() => {
    const fetch = async () => {
      try {
        const { count } = await getUnreadCount();
        setUnread(count);
      } catch { /* ignore */ }
      if (openRef.current) {
        listNotifications({ is_read: false, limit: 5 }).then((r) => setNotifications(r.items)).catch(() => {});
      }
    };
    fetch();
    const interval = setInterval(fetch, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (open) {
      listNotifications({ is_read: false, limit: 5 }).then((r) => setNotifications(r.items)).catch(() => {});
    }
  }, [open]);
```

(Keep the second effect too — it still needs to fire immediately on open, not wait up to 30s
for the interval.)

- [ ] **Step 2: Manual verification**

Open the bell dropdown, then trigger a notification for that user from another session/tab
(e.g. have a peer offer to cover one of their swaps), and confirm the list updates within
30 seconds without closing/reopening the dropdown.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/NotificationBell.tsx
git commit -m "fix: refresh the open notification bell list on the same interval as the unread count"
```

---

### Task 12: Surface excluded/ineligible soldiers inline in the range assignment modal

**Files:**
- Modify: `backend/app/services/range_auto_assign.py:175-379`
- Modify: `backend/app/routes/ranges.py` (around line 574, the `/candidates` route)
- Modify: `frontend/src/api/ranges.ts` (candidate response type)
- Modify: `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx` (`CandidateTable`,
  lines ~428-478)
- Test: `backend/tests/unit/...` (find the existing test file for `range_auto_assign.py` and
  add a case there)

**Context:** `_bulk_eligibility` (`range_auto_assign.py:175-269`) silently omits soldiers who
are weapon-exempt, structurally ineligible, or already assigned to another range the same
day — by design, since they can never actually be assigned. But the frontend
(`RangeEditAssignmentsModal.tsx`) has no way to show *that* soldiers were excluded or *why* —
the only place that information exists is the separate "כשירות" tab
(`RangesPage.tsx:135`), which requires navigating away from the assignment modal.

- [ ] **Step 1: Read the current test file for this module**

Find the existing test file (likely `backend/tests/unit/algorithm/` or
`backend/tests/unit/services/` — search for `range_auto_assign` or `rank_candidates`) and read
it to match its fixture/mocking conventions before writing new test code.

- [ ] **Step 2: Make `_bulk_eligibility` also return why soldiers were excluded**

In `backend/app/services/range_auto_assign.py`, change `_bulk_eligibility`'s return type from
`dict[uuid.UUID, str | None]` to a small dataclass or tuple that also carries excluded
soldiers with a reason code. Add near the top of the file (or reuse an existing similar
pattern if one exists elsewhere in this module — check first):

```python
@dataclass(frozen=True)
class ExcludedSoldier:
    soldier_id: uuid.UUID
    reason: Literal["weapon_exempt", "structurally_ineligible", "assigned_elsewhere_same_day"]
```

Change the loop at line 256-269 (`for soldier in soldiers: ... if soldier.id in exempted or
structurally_exempt or soldier.id in at_other_range: continue`) to record *why* instead of
just `continue`-ing:

```python
    excluded: list[ExcludedSoldier] = []
    result: dict[uuid.UUID, str | None] = {}
    for soldier in soldiers:
        node = nodes_by_id.get(soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
        structurally_exempt = node is None or not any(
            node_in_scope(dt.eligible_node_ids, node.path_ids) for dt in weapon_duty_types
        )
        if soldier.id in exempted:
            excluded.append(ExcludedSoldier(soldier.id, "weapon_exempt"))
            continue
        if structurally_exempt:
            excluded.append(ExcludedSoldier(soldier.id, "structurally_ineligible"))
            continue
        if soldier.id in at_other_range:
            excluded.append(ExcludedSoldier(soldier.id, "assigned_elsewhere_same_day"))
            continue
        # ... existing constraint/duty_conflict handling below, unchanged
```

Change the function's return to `tuple[dict[uuid.UUID, str | None], list[ExcludedSoldier]]`
and update its one caller (`rank_candidates`, line 361-363) to unpack both.

- [ ] **Step 3: Expose the exclusion summary from `rank_candidates`**

`rank_candidates` currently returns `list[RankedCandidate]`. Add a sibling return value —
either change its signature to return `tuple[list[RankedCandidate], list[ExcludedSoldier]]`,
or (less invasive) add a second function `excluded_candidates(session, *, event, user) ->
list[ExcludedSoldier]` that repeats the soldier-pool + `_bulk_eligibility` call and returns
just the excluded list. Prefer changing `rank_candidates`'s return type directly if its one
call site (the `/candidates` route) is easy to update — check that route first.

- [ ] **Step 4: Add soldier names to the excluded list and expose via the API**

In `backend/app/routes/ranges.py` around the `/candidates` route (line 574), extend the
response — add a new field to whatever Pydantic model wraps `RangeCandidateOut`, e.g.
`excluded: list[ExcludedSoldierOut]` where `ExcludedSoldierOut` has `soldier_id`,
`soldier_name`, and `reason` (translate the reason code to the same Hebrew categories the
frontend will show, or keep it as a code and translate client-side via i18n — prefer
client-side translation for consistency with the rest of the app's error-code pattern from
Task 4).

- [ ] **Step 5: Write a backend test**

Add a test to the file found in Step 1 that creates one weapon-exempt soldier, one
structurally-ineligible soldier, and one soldier already assigned to another range that day,
calls `rank_candidates` (or the new `excluded_candidates` function), and asserts each shows up
in the excluded list with the correct reason and none appear in the ranked/eligible list.

- [ ] **Step 6: Run the backend test**

Run: `cd backend && uv run pytest tests/unit/<path-from-step-1> -v -k excluded`
Expected: PASS.

- [ ] **Step 7: Add the frontend type and a collapsed "excluded" row in the modal**

In `frontend/src/api/ranges.ts`, extend the candidates response type to include the new
`excluded` array. In `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx`'s
`CandidateTable` (lines ~428-478), add a collapsed summary row below the candidate list, e.g.:

```typescript
{excluded.length > 0 && (
  <details className="text-xs text-gray-500 dark:text-gray-400 mt-2">
    <summary className="cursor-pointer">{excluded.length} חיילים לא הוצגו — הצג סיבה</summary>
    <ul className="mt-1 space-y-0.5">
      {excluded.map((x) => (
        <li key={x.soldier_id}>{x.soldier_name}: {t(`ranges.excluded_reason.${x.reason}`)}</li>
      ))}
    </ul>
  </details>
)}
```

Add the three reason translations to `he.json` under a new `ranges.excluded_reason` object:
`weapon_exempt` → "פטור מנשק", `structurally_ineligible` → "לא כשיר מבנית לתפקידי נשק",
`assigned_elsewhere_same_day` → "משובץ למטווח אחר באותו יום".

- [ ] **Step 8: Manual verification**

Open the assignment modal for a range event where at least one candidate soldier is
weapon-exempt or already booked elsewhere that day, confirm the collapsed "X חיילים לא הוצגו"
row appears with the correct count and reasons, and that it matches the "כשירות" tab's data
for the same soldiers.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/range_auto_assign.py backend/app/routes/ranges.py backend/tests/unit/<path> frontend/src/api/ranges.ts frontend/src/components/ranges/RangeEditAssignmentsModal.tsx frontend/src/i18n/he.json
git commit -m "feat: surface excluded/ineligible soldiers inline in the range assignment modal"
```

---

### Task 13: Consolidate the three names for the open-swap-board feature

**Files:**
- Modify: `frontend/src/i18n/he.json`

**Context:** `he.json` has `swaps.board` = "לוח מחליפים" (line 900, **confirmed dead — no
component references it**, verified via grep), `swaps.tab_board` = "מרקטפלייס" (line 928, the
actual visible tab label), and two separate `already_on_marketplace` messages both saying
"...שוק ההחלפות" (lines 574 and 996). Standardize on "מרקטפלייס" since that's what users
already see on the tab.

- [ ] **Step 1: Delete the dead key**

In `frontend/src/i18n/he.json`, delete line 900 (`"board": "לוח מחליפים",`) from the `swaps`
object. Re-grep for `swaps.board`/`t("swaps.board")` across `frontend/src` first to be
certain nothing uses it (the earlier audit already did this and found zero matches, but
re-verify since the codebase may have changed).

- [ ] **Step 2: Reword the two `already_on_marketplace` messages**

Change line 574 (under `errors`) from:
```json
    "already_on_marketplace": "הבקשה כבר פורסמה בשוק ההחלפות",
```
to:
```json
    "already_on_marketplace": "הבקשה כבר פורסמה במרקטפלייס",
```

Change line 996 (under `swaps`) from:
```json
    "already_on_marketplace": "כבר פורסם בשוק ההחלפות",
```
to:
```json
    "already_on_marketplace": "כבר פורסם במרקטפלייס",
```

- [ ] **Step 3: Update the audit doc's own reference (optional but keeps docs accurate)**

If `docs/onboarding/user-guide.md` or `README.md` still calls the feature "לוח מחליפים"
anywhere, update those mentions to "מרקטפלייס" too, for consistency between docs and UI. Grep
for "לוח מחליפים" across `docs/` and `README.md` before editing.

- [ ] **Step 4: Manual verification**

Trigger the "already published" error (try to re-publish an already-marketplace-listed swap)
and confirm it now says "...במרקטפלייס".

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "fix: use one consistent name (מרקטפלייס) for the open swap board everywhere"
```

---

## Tier 3 tasks

### Task 14: Migrate `RangesPage.tsx`'s hardcoded Hebrew strings to `he.json`

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/i18n/he.json`

**Depends on:** Do this **after** Task 3 (duplicate option) and Task 8 (ConfirmDialog
migration) if both are being done, since this task will move the strings those tasks touch —
doing it last avoids merge friction between tasks.

**Context:** Every other major page routes its Hebrew copy through `t("...")` /
`he.json`— `RangesPage.tsx` (156 lines, confirmed via full read) hardcodes every string inline
instead. This is what let the duplicate `<option>` in Task 3 go unnoticed (no single source of
truth to diff against), and makes any future "מטווח" terminology change a grep-and-replace
across component files instead of one JSON edit.

- [ ] **Step 1: List every hardcoded Hebrew string literal in the file**

Read the full current `frontend/src/pages/RangesPage.tsx` (post Tasks 3/8) and list every
Hebrew string literal that isn't already going through `t()` — button labels, filter labels,
column headers, confirmation/error messages, the "מטווחים" page title, tab-adjacent text. Do
not include strings inside child components (`RangePlanningTable`, `RangeDetailContent`,
etc.) — this task is scoped to `RangesPage.tsx` itself.

- [ ] **Step 2: Add a `ranges` namespace to `he.json` with one key per string**

Add a new top-level `ranges` object to `he.json` (check it doesn't already exist and collide —
`ranges.excluded_reason` may already exist if Task 12 ran first; add alongside it, not over
it) with one key per string found in Step 1, named descriptively
(`page_title`, `create_button`, `export_link`, `import_link`, `filter_status_label`,
`filter_status_all`, `bulk_selected_count`, `bulk_clear_button`, `bulk_cancel_button`,
`bulk_delete_button`, `view_assignments_button`, `edit_button`, `delete_button`,
`cancel_button`, `filter_from_date`, `filter_to_date`, `filter_type_label`,
`filter_type_all`, `filter_fill_label`, `filter_fill_all`, `filter_fill_open`,
`filter_fill_full`, `sort_by_date`, `load_error`, `confirm_delete_no_deletable`,
`confirm_bulk_delete_title`, `confirm_bulk_delete_message`, `confirm_bulk_clear_title`,
`confirm_bulk_clear_message`, `confirm_bulk_clear_reason_label`,
`confirm_single_delete_title`, `confirm_single_delete_message`, `bulk_delete_error`,
`bulk_cancel_error`, `bulk_clear_error`, `status_column_label`, etc. — match exactly to what
Step 1 found; this list is illustrative, not exhaustive).

- [ ] **Step 3: Replace each literal in `RangesPage.tsx` with `t("ranges.<key>")`**

Import `useTranslation` (if the existing `t` from the file's current single usage isn't
already destructured at the top — check first) and replace each string found in Step 1 with
its `t()` call, one at a time, keeping the visible text byte-for-byte identical to what
`he.json` now holds (no wording changes in this task — that's out of scope; only where the
text lives changes).

- [ ] **Step 4: Verify no visible text changed**

Run the dev app, open the ranges page and each of its filters/dialogs/buttons, and compare
against a text dump taken before this task started (e.g. via
`get_page_text`/`document.body.innerText` on the ranges page before and after — every string
should match exactly).

- [ ] **Step 5: Run typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/RangesPage.tsx frontend/src/i18n/he.json
git commit -m "refactor: move RangesPage's hardcoded Hebrew strings into he.json"
```

---

### Task 15: Deep-link the מטווחים/אל"ל warning banners to their specific profile field

**Files:**
- Modify: `frontend/src/components/dashboard/AlertBanners.tsx:108`
- Modify: `frontend/src/pages/ProfilePage.tsx`

**Context:** The banner already navigates to `/profile` on click (confirmed via code read —
this is **not** a "missing CTA" as originally suspected). The gap is narrower: it lands at the
top of the profile page instead of scrolling to the specific מטווחים or אל"ל field, so on a
long profile page the user still has to hunt for the right field.

- [ ] **Step 1: Add stable ids to the two profile fields**

In `frontend/src/pages/ProfilePage.tsx`, find the "מטווחים אחרון" and "אל"ל אחרון" field
wrappers (labeled the same way as seen in the audit — the fields with a `📅` date-picker
button and a "שלח בקשת עדכון" button next to them) and add
`id="last-mitvahim-field"` / `id="last-alal-field"` to each field's wrapping `<div>` (not the
input itself, so the highlight in Step 3 can wrap the whole label+input+button group).

- [ ] **Step 2: Pass which field to scroll to from the banner**

In `frontend/src/components/dashboard/AlertBanners.tsx`, change the `onClick` at line 108 from:

```typescript
          onClick={() => navigate("/profile")}
```

to:

```typescript
          onClick={() => navigate(`/profile#${a.key === "alal" ? "last-alal-field" : "last-mitvahim-field"}`)}
```

- [ ] **Step 3: Scroll to and briefly highlight the target field on `ProfilePage` mount**

In `frontend/src/pages/ProfilePage.tsx`, add an effect (near the top of the component, after
other hooks) that reads `location.hash` and scrolls the matching element into view with a
brief highlight:

```typescript
  const location = useLocation(); // import from react-router-dom if not already imported
  useEffect(() => {
    if (!location.hash) return;
    const id = location.hash.slice(1);
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("ring-2", "ring-amber-400", "rounded");
    const timeout = setTimeout(() => el.classList.remove("ring-2", "ring-amber-400", "rounded"), 2500);
    return () => clearTimeout(timeout);
  }, [location.hash]);
```

- [ ] **Step 4: Manual verification**

As a soldier with an outdated מטווחים or אל"ל date, click the warning banner and confirm the
page scrolls to and briefly highlights the correct field instead of just landing at the top of
the profile page.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/AlertBanners.tsx frontend/src/pages/ProfilePage.tsx
git commit -m "fix: scroll to the specific field when clicking a מטווחים/אל\"ל warning banner"
```

---

## Self-review notes (for whoever executes this plan)

- Tasks 1, 9, 10 all touch `UnifiedNav.tsx` / `ApprovalsPage.tsx` — if run by different
  subagents in parallel, expect a merge conflict; consider serializing those three, or
  explicitly telling each subagent which lines the others are touching.
- Task 12 is the largest/riskiest (backend service contract change) — review its diff
  especially carefully for callers of `_bulk_eligibility`/`rank_candidates` this plan didn't
  find (re-grep before merging).
- Tasks 3, 8, and 14 all touch `RangesPage.tsx` — do them in that order (3 → 8 → 14) in a
  single lineage, not in parallel, or later tasks will conflict with earlier ones' diffs.
- After all tasks land, re-run the two corrected/dropped findings' repro steps one more time
  (the AskSwapModal duplicate-request error, and the take_free/claim_request notification
  text) to make sure nothing in this plan's other changes accidentally regressed them.
