# Plan E — Small Feature Additions

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three self-contained features: indefinite exemption UI, "למה קיבלתי?" button on duty rows, and swap eligibility validation in the offer modal.

**Architecture:** Backend-only for the eligibility endpoint. Frontend-only for indefinite exemption checkbox and explanation button wiring. Depends on `ExplanationModal` redesign (Plan D Task 4) for the best UX, but can be implemented independently with the existing modal.

**Tech Stack:** React, Tailwind, FastAPI, SQLAlchemy

---

### Task 1: Indefinite exemption checkbox

**Files:**
- Modify: `frontend/src/components/ExemptionsPanel.tsx`

**Current state:** `ExemptionsPanel` already sends `end_date: end || null` — the backend already accepts `null`. The only change needed is a checkbox UI to make "indefinite" an explicit opt-in and disable the date picker.

- [ ] **Step 1: Add `indefinite` state and checkbox**

In `frontend/src/components/ExemptionsPanel.tsx`, add state:
```tsx
const [indefinite, setIndefinite] = useState(false);
```

In the grant form, after the start-date input, replace the end-date input with:
```tsx
<div className="flex items-center gap-2">
  <input
    type="date"
    className={`border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 ${indefinite ? "opacity-40 cursor-not-allowed" : ""}`}
    value={indefinite ? "" : end}
    onChange={(e) => setEnd(e.target.value)}
    disabled={indefinite}
    data-testid="grant-end"
  />
  <label className="flex items-center gap-1 text-sm whitespace-nowrap cursor-pointer">
    <input
      type="checkbox"
      checked={indefinite}
      onChange={(e) => {
        setIndefinite(e.target.checked);
        if (e.target.checked) setEnd("");
      }}
      data-testid="grant-indefinite"
    />
    ללא הגבלת זמן
  </label>
</div>
```

The existing `onGrant` already sends `end_date: end || null`, so when `end` is `""` and `indefinite` is `true`, it sends `null` — no further changes needed in the submit handler.

Reset `indefinite` to `false` in `onGrant` after successful grant:
```tsx
setIndefinite(false);
```

- [ ] **Step 2: Update display of indefinite exemptions**

In the exemptions list rendering, the component already uses `ex.end_date ?? t("exemptions.forever")`. Verify `he.json` has `"exemptions": { "forever": "ללא הגבלה" }`. Add if missing:
```json
"exemptions": {
  "forever": "ללא הגבלה"
}
```

- [ ] **Step 3: Write a vitest test**

In `frontend/src/components/ExemptionsPanel.test.tsx` (create if missing):
```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import ExemptionsPanel from "./ExemptionsPanel";
// mock the API calls

test("indefinite checkbox disables end-date picker", () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} />);
  const checkbox = screen.getByTestId("grant-indefinite");
  const endInput = screen.getByTestId("grant-end");
  expect(endInput).not.toBeDisabled();
  fireEvent.click(checkbox);
  expect(endInput).toBeDisabled();
});
```

Run: `cd frontend && pnpm test ExemptionsPanel`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ExemptionsPanel.tsx frontend/src/i18n/he.json
git commit -m "feat: indefinite exemption checkbox disables date picker, sends null end_date"
```

---

### Task 2: "למה קיבלתי?" button per duty row

**Files:**
- Modify: `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx`
- Modify: `frontend/src/components/dashboard/DutyDetailModal.tsx`
- Modify: `frontend/src/pages/DutyManagementPage.tsx`

**Note:** This task adds a `?` trigger button. It opens `ExplanationModal` from Plan D. If Plan D is not done, the existing modal will open instead — still works, just less polished.

- [ ] **Step 1: Add `?` button to `UpcomingDutiesWidget` rows**

In `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx`, add state:
```tsx
import ExplanationModal from "../ExplanationModal";
const [explanationId, setExplanationId] = useState<string | null>(null);
```

In each table row, add a fourth column with the `?` button:
```tsx
<td className="py-2 w-8 text-center">
  <button
    className="text-gray-400 hover:text-indigo-600 text-xs font-bold border border-gray-300 dark:border-gray-600 rounded-full w-5 h-5 inline-flex items-center justify-center"
    onClick={(e) => { e.stopPropagation(); setExplanationId(d.assignment_id); }}
    title="למה קיבלתי תורנות זו?"
  >
    ?
  </button>
</td>
```

Add the modal at the bottom of the component:
```tsx
<ExplanationModal
  assignmentId={explanationId}
  onClose={() => setExplanationId(null)}
/>
```

- [ ] **Step 2: Add `?` button inside `DutyDetailModal`**

In `frontend/src/components/dashboard/DutyDetailModal.tsx`, add an explanation button below the "בקש החלפה" button:
```tsx
import ExplanationModal from "../ExplanationModal";
const [showExplanation, setShowExplanation] = useState(false);

// In JSX, below the swap button:
<button
  className="w-full border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 py-2 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
  onClick={() => setShowExplanation(true)}
>
  למה קיבלתי? ›
</button>
{showExplanation && (
  <ExplanationModal
    assignmentId={duty.assignment_id}
    onClose={() => setShowExplanation(false)}
  />
)}
```

- [ ] **Step 3: Add `?` button in `DutyManagementPage` assignment rows**

In `frontend/src/pages/DutyManagementPage.tsx`, find the assignment rows table. Add a `?` button per row that opens `ExplanationModal` with that assignment's ID.

```tsx
import ExplanationModal from "../components/ExplanationModal";
const [explanationId, setExplanationId] = useState<string | null>(null);

// In the rows table, add a column:
<button
  className="text-gray-400 hover:text-indigo-600 text-xs"
  onClick={() => setExplanationId(row.id)}
  title="למה קיבל חייל זה תורנות זו?"
>
  ?
</button>

// At bottom of component:
<ExplanationModal assignmentId={explanationId} onClose={() => setExplanationId(null)} />
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/dashboard/UpcomingDutiesWidget.tsx frontend/src/components/dashboard/DutyDetailModal.tsx frontend/src/pages/DutyManagementPage.tsx
git commit -m "feat: why-did-I-get-this button on duty rows and detail modal"
```

---

### Task 3: Swap eligibility validation

**Files:**
- Create: `backend/app/routes/swaps_eligibility.py`
- Modify: `backend/app/main.py` (register router)
- Modify: `frontend/src/api/swaps.ts`
- Modify: `frontend/src/components/OfferSwapModal.tsx`

- [ ] **Step 1: Create eligibility endpoint**

Create `backend/app/routes/swaps_eligibility.py`:
```python
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.auth.deps import require_password_changed
from app.db.models import (
    DutyAssignment, DutyShift, PersonalConstraint, Soldier, SoldierExemption,
    ExemptionDutyTypeMap, ExemptionType,
)
from app.db.session import get_session
from app.services.eligibility import compute_eligibility_exclusions

router = APIRouter(prefix="/swaps", tags=["swaps"])


class EligibilityResult(BaseModel):
    assignment_id: uuid.UUID
    eligible: bool
    reason: str | None


@router.get("/eligible-duties", response_model=list[EligibilityResult])
def eligible_duties(
    target_soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    """
    For each of the current user's published/active assignments, check whether
    target_soldier_id would be eligible to accept a swap for it.
    """
    today = date.today()
    my_assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.soldier_id == actor.id,
            DutyAssignment.status == "published",
            DutyAssignment.end_date >= today,
        )
    ).scalars().all()

    target = session.get(Soldier, target_soldier_id)
    if target is None:
        return []

    # Collect target's approved constraints
    target_constraints = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == target_soldier_id,
            PersonalConstraint.status == "approved",
        )
    ).scalars().all()

    # Collect target's active exemptions
    target_exemptions = session.execute(
        select(SoldierExemption).where(
            SoldierExemption.soldier_id == target_soldier_id,
        )
    ).scalars().all()

    # Eligibility exclusions (mitvahim/alal)
    exclusions = compute_eligibility_exclusions(session, [target])
    excluded_dtype_ids = exclusions.get(target_soldier_id, set())

    # Build exempt duty type set from active exemptions
    exempted_dtype_ids: set[uuid.UUID] = set()
    for ex in target_exemptions:
        if ex.start_date <= today and (ex.end_date is None or ex.end_date >= today):
            rows = session.execute(
                select(ExemptionDutyTypeMap.duty_type_id).where(
                    ExemptionDutyTypeMap.exemption_type_id == ex.exemption_type_id
                )
            ).scalars().all()
            exempted_dtype_ids.update(rows)
            # Check if global
            et = session.get(ExemptionType, ex.exemption_type_id)
            if et and et.is_global:
                from sqlalchemy import select as sa_select
                from app.db.models import DutyType
                all_dt = session.execute(sa_select(DutyType.id)).scalars().all()
                exempted_dtype_ids.update(all_dt)

    results = []
    for a in my_assignments:
        # Check duty type exemption
        if a.duty_type_id in exempted_dtype_ids:
            results.append(EligibilityResult(
                assignment_id=a.id,
                eligible=False,
                reason="פטור מסוג תורנות זו",
            ))
            continue

        # Check eligibility exclusions
        if a.duty_type_id in excluded_dtype_ids:
            results.append(EligibilityResult(
                assignment_id=a.id,
                eligible=False,
                reason="אי-כשירות זמנית (מיטבחים / אל\"ל)",
            ))
            continue

        # Check personal constraint overlap
        conflict = next(
            (c for c in target_constraints
             if c.start_date <= a.end_date and c.end_date >= a.start_date),
            None,
        )
        if conflict:
            results.append(EligibilityResult(
                assignment_id=a.id,
                eligible=False,
                reason="אילוץ אישי מאושר בתאריך זה",
            ))
            continue

        results.append(EligibilityResult(assignment_id=a.id, eligible=True, reason=None))

    return results
```

- [ ] **Step 2: Register router**

In `backend/app/main.py`:
```python
from app.routes.swaps_eligibility import router as swaps_eligibility_router
app.include_router(swaps_eligibility_router)
```

- [ ] **Step 3: Write backend test**

In `backend/tests/integration/test_swaps_eligibility.py` (create):
```python
def test_eligible_duties_exemption(client, soldier_token, target_soldier_id, assignment_id, exemption_for_target):
    resp = client.get(
        f"/swaps/eligible-duties?target_soldier_id={target_soldier_id}",
        headers={"Authorization": f"Bearer {soldier_token}"},
    )
    assert resp.status_code == 200
    results = resp.json()
    match = next((r for r in results if r["assignment_id"] == str(assignment_id)), None)
    assert match is not None
    assert match["eligible"] is False
    assert "פטור" in match["reason"]
```

Run: `cd backend && uv run pytest tests/integration/test_swaps_eligibility.py -v`
Expected: PASS.

- [ ] **Step 4: Add API function to `swaps.ts`**

In `frontend/src/api/swaps.ts`:
```ts
export interface EligibilityResult {
  assignment_id: string;
  eligible: boolean;
  reason: string | null;
}

export async function getEligibleDuties(targetSoldierId: string): Promise<EligibilityResult[]> {
  return (await api.get<EligibilityResult[]>("/swaps/eligible-duties", {
    params: { target_soldier_id: targetSoldierId },
  })).data;
}
```

- [ ] **Step 5: Update `OfferSwapModal` to show eligibility**

In `frontend/src/components/OfferSwapModal.tsx`, add:
```tsx
import { EligibilityResult, getEligibleDuties } from "../api/swaps";

// State:
const [eligibility, setEligibility] = useState<Record<string, EligibilityResult>>({});
const [eligibilityLoading, setEligibilityLoading] = useState(false);

// When target soldier is selected:
useEffect(() => {
  if (!targetSoldierId) return;
  setEligibilityLoading(true);
  getEligibleDuties(targetSoldierId)
    .then((results) => {
      setEligibility(Object.fromEntries(results.map((r) => [r.assignment_id, r])));
    })
    .catch(() => {})
    .finally(() => setEligibilityLoading(false));
}, [targetSoldierId]);
```

For each duty option in the modal, wrap with eligibility check:
```tsx
{myDuties.map((duty) => {
  const elig = eligibility[duty.assignment_id];
  const isIneligible = elig && !elig.eligible;
  const isMobile = navigator.maxTouchPoints > 0;

  return (
    <label
      key={duty.assignment_id}
      className={`flex items-center gap-2 p-2 rounded border cursor-pointer
        ${isIneligible
          ? "opacity-50 cursor-not-allowed border-gray-200 dark:border-gray-700"
          : "border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700"}`}
      title={isIneligible && !isMobile ? (elig.reason ?? undefined) : undefined}
      onClick={(e) => {
        if (isIneligible && isMobile) {
          e.preventDefault();
          // Show toast
          alert(elig?.reason ?? "חייל זה אינו יכול לקבל תורנות זו");
        }
      }}
    >
      <input
        type="radio"
        name="offered_duty"
        value={duty.assignment_id}
        disabled={isIneligible}
        onChange={() => setSelectedDutyId(duty.assignment_id)}
      />
      <span>{typeNames[duty.duty_type_id] ?? "תורנות"} — {formatDateRange(duty.start_date, duty.end_date)}</span>
    </label>
  );
})}
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/swaps_eligibility.py backend/app/main.py frontend/src/api/swaps.ts frontend/src/components/OfferSwapModal.tsx
git commit -m "feat: swap offer modal greys out ineligible duties with reason tooltip"
```
