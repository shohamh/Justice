# Plan D — Transparency & Fairness Accuracy

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four transparency/fairness issues: make `enrolled_at` editable so active days diverge correctly, show exempted-soldier effect on unit percentages, sort Excel export by hierarchy, and redesign the "למה קיבלתי?" explanation.

**Architecture:** Backend changes to scoring aggregation and soldier update routes. Frontend changes to soldier edit modal, transparency page, and `ExplanationModal`. No new DB migrations needed (all fields already exist).

**Tech Stack:** React, Tailwind, FastAPI, SQLAlchemy, openpyxl

---

### Task 1: Make `enrolled_at` editable in soldier profile

**Files:**
- Modify: `backend/app/routes/soldiers.py` (allow `enrolled_at` in PATCH)
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx` (add field)

- [ ] **Step 1: Check current PATCH schema**

Read `backend/app/routes/soldiers.py`. Find the `SoldierUpdateRequest` Pydantic model. Check if `enrolled_at` is present. It likely is not.

- [ ] **Step 2: Add `enrolled_at` to update schema**

In `backend/app/routes/soldiers.py`, in `SoldierUpdateRequest`:
```python
from datetime import date as date_type

class SoldierUpdateRequest(BaseModel):
    # ... existing fields ...
    enrolled_at: date_type | None = None
```

In the PATCH handler, where the soldier is updated, add:
```python
if req.enrolled_at is not None:
    soldier.enrolled_at = req.enrolled_at
```

- [ ] **Step 3: Write test**

In `backend/tests/integration/test_soldiers.py` (or create), add:
```python
def test_patch_enrolled_at(client, commander_token, soldier_id):
    resp = client.patch(
        f"/soldiers/{soldier_id}",
        json={"enrolled_at": "2024-01-15"},
        headers={"Authorization": f"Bearer {commander_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["enrolled_at"] == "2024-01-15"
```

Run: `cd backend && uv run pytest tests/integration/test_soldiers.py -v -k enrolled_at`
Expected: PASS.

- [ ] **Step 4: Add field to `UnifiedSoldierModal`**

In `frontend/src/components/UnifiedSoldierModal.tsx`, find the form fields for editing a soldier. Add an `enrolled_at` date input, visible only to commanders and admins:
```tsx
{canManage && (
  <div>
    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
      תאריך הצטרפות ליחידה
    </label>
    <input
      type="date"
      className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
      value={enrolledAt}
      onChange={(e) => setEnrolledAt(e.target.value)}
      data-testid="enrolled-at-input"
    />
  </div>
)}
```

Add `enrolledAt` state initialized from `soldier.enrolled_at`. Include it in the PATCH payload.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/soldiers.py frontend/src/components/UnifiedSoldierModal.tsx
git commit -m "feat: enrolled_at editable by commanders in soldier profile"
```

---

### Task 2: Exemption effect on transparency unit percentages

**Files:**
- Modify: `backend/app/routes/scoring.py` (subunits aggregation)
- Modify: `frontend/src/pages/TransparencyPage.tsx` (subunits table)

- [ ] **Step 1: Read current subunits aggregation**

In `backend/app/routes/scoring.py`, find the subunits endpoint (likely `GET /scoring/subunits` or similar). Read how `active_count` is computed per node.

- [ ] **Step 2: Add `exempted_count` to the response**

In the subunits endpoint, for each hierarchy node, compute:
```python
from datetime import date
today = date.today()

# A soldier is "fully exempted" today if they have any SoldierExemption
# where exemption_type.is_global=True (or covers all active duty types)
# and start_date <= today <= (end_date or far future)

exempted_ids = {
    ex.soldier_id
    for ex in session.execute(
        select(SoldierExemption)
        .join(ExemptionType)
        .where(
            ExemptionType.is_global.is_(True),
            SoldierExemption.start_date <= today,
            sa.or_(
                SoldierExemption.end_date.is_(None),
                SoldierExemption.end_date >= today,
            ),
        )
    ).scalars().all()
}
```

Then per node:
```python
node_soldiers = [s for s in soldiers if s.hierarchy_node_id == node.id]
active_count = sum(1 for s in node_soldiers if s.id not in exempted_ids)
exempted_count = sum(1 for s in node_soldiers if s.id in exempted_ids)
```

Add `exempted_count: int` to the response model.

- [ ] **Step 3: Update frontend subunits table**

In `frontend/src/pages/TransparencyPage.tsx`, find the subunits table columns. Add an "ממוצרים" (exempted) column showing the count, and update the "% active" calculation to use `active_count / total` where `active_count = total - exempted_count`.

Add a tooltip on the exempted count cell:
```tsx
<td
  className="py-2 text-center text-gray-500"
  title={`${row.exempted_count} חיילים פטורים`}
>
  {row.exempted_count}
</td>
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/scoring.py frontend/src/pages/TransparencyPage.tsx
git commit -m "feat: transparency subunits shows exempted count, % active is accurate"
```

---

### Task 3: Excel export sorted by hierarchy

**Files:**
- Modify: `backend/app/routes/scoring.py` (export handler)

- [ ] **Step 1: Read the export handler**

In `backend/app/routes/scoring.py`, find `downloadSubUnitsExport` or the Excel export endpoint. Read how rows are ordered.

- [ ] **Step 2: Add DFS sort before writing rows**

Import the hierarchy service:
```python
from app.services import hierarchy as hierarchy_svc
```

Before writing rows to the workbook:
```python
# Build DFS-ordered node list
tree = hierarchy_svc.get_tree(session)

def dfs_order(nodes) -> list:
    result = []
    for node in nodes:
        result.append(node.id)
        result.extend(dfs_order(node.children or []))
    return result

ordered_node_ids = dfs_order(tree)
node_order = {nid: i for i, nid in enumerate(ordered_node_ids)}

# Sort rows by node order, then by soldier name within each node
rows.sort(key=lambda r: (node_order.get(r.node_id, 9999), r.full_name))
```

- [ ] **Step 3: Add hierarchy path column**

When writing header row, add "יחידה / תת-יחידה" as the first column. Build the path for each soldier:
```python
def node_path(node_id, nodes_by_id: dict, sep=" / ") -> str:
    parts = []
    nid = node_id
    while nid:
        node = nodes_by_id.get(nid)
        if not node:
            break
        parts.append(node.name)
        nid = node.parent_id
    return sep.join(reversed(parts))
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/scoring.py
git commit -m "fix: transparency Excel export sorted by DFS hierarchy order with path column"
```

---

### Task 4: Redesign "למה קיבלתי?" explanation modal

**Files:**
- Modify: `frontend/src/components/ExplanationModal.tsx`
- Modify: `backend/app/algorithm/types.py` (verify `ExplanationData` has ranked candidates)
- Modify: `backend/app/routes/assignments.py` (verify explanation endpoint)

- [ ] **Step 1: Check what `ExplanationData` contains**

Read `backend/app/algorithm/types.py`. Find `ExplanationData` or `AssignmentExplanation`. Check if it stores ranked candidates (list of other soldiers considered with their scores).

- [ ] **Step 2: Extend `ExplanationData` if needed**

If `ExplanationData` does not have a `ranked_candidates` field, add it:
```python
@dataclass
class CandidateSnapshot:
    soldier_id: uuid.UUID
    full_name: str
    score: Decimal
    reason_excluded: str | None  # None means they were eligible but ranked lower

@dataclass
class ExplanationData:
    # existing fields ...
    ranked_candidates: list[CandidateSnapshot] = field(default_factory=list)
    eligible_count: int = 0
    soldier_rank: int = 1  # 1 = best (lowest score), assigned this duty
```

Update the algorithm bridge where `AssignmentExplanation` records are created to populate these fields.

- [ ] **Step 3: Update the explanation API response**

In `backend/app/routes/assignments.py`, find `GET /assignments/{id}/explanation`. Ensure the response includes `ranked_candidates`, `eligible_count`, and `soldier_rank`.

- [ ] **Step 4: Redesign `ExplanationModal.tsx`**

Replace the existing component:
```tsx
import { useEffect, useState } from "react";
import { api } from "../api/client";

interface CandidateSnapshot {
  soldier_id: string;
  full_name: string;
  score: number;
  reason_excluded: string | null;
}

interface ExplanationData {
  soldier_name: string;
  score_at_assignment: number;
  eligible_count: number;
  soldier_rank: number;
  ranked_candidates: CandidateSnapshot[];
  constraint_count: number;
}

interface Props {
  assignmentId: string | null;
  onClose: () => void;
}

export default function ExplanationModal({ assignmentId, onClose }: Props) {
  const [data, setData] = useState<ExplanationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [manual, setManual] = useState(false);

  useEffect(() => {
    if (!assignmentId) return;
    setLoading(true);
    api.get(`/assignments/${assignmentId}/explanation`)
      .then((r) => {
        if (r.data === null || r.data.eligible_count === 0) setManual(true);
        else setData(r.data as ExplanationData);
      })
      .catch(() => setManual(true))
      .finally(() => setLoading(false));
  }, [assignmentId]);

  if (!assignmentId) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-5 max-w-lg w-full mx-4 space-y-4 text-sm max-h-[90vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="text-base font-semibold">למה קיבלתי תורנות זו?</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        {loading && <p className="text-gray-500">טוען...</p>}

        {manual && !loading && (
          <p className="text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-700 rounded p-3">
            תורנות זו שובצה ידנית — אין הסבר אלגוריתמי.
          </p>
        )}

        {data && !loading && (
          <>
            {/* Summary */}
            <div className="bg-indigo-50 dark:bg-indigo-950 rounded p-3 font-medium text-indigo-700 dark:text-indigo-300">
              קיבלת תורנות זו כי היה לך הניקוד הנמוך ביותר מבין {data.eligible_count} חיילים כשירים בתאריך זה.
            </div>

            {/* Standing */}
            <div>
              <p className="font-medium text-gray-700 dark:text-gray-300 mb-2">המצב שלך בעת השיבוץ:</p>
              <table className="w-full text-xs border-collapse">
                <tbody>
                  <tr className="border-b dark:border-gray-700">
                    <td className="py-1 text-gray-500 w-40">ניקוד מצטבר</td>
                    <td className="py-1 font-medium">{data.score_at_assignment.toFixed(1)}</td>
                  </tr>
                  <tr className="border-b dark:border-gray-700">
                    <td className="py-1 text-gray-500">דירוג בין כשירים</td>
                    <td className="py-1 font-medium">{data.soldier_rank} / {data.eligible_count}</td>
                  </tr>
                  <tr>
                    <td className="py-1 text-gray-500">אילוצים פעילים</td>
                    <td className="py-1 font-medium">{data.constraint_count === 0 ? "אין" : data.constraint_count}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Rejected candidates */}
            {data.ranked_candidates.length > 0 && (
              <div>
                <p className="font-medium text-gray-700 dark:text-gray-300 mb-2">מדוע אחרים לא נבחרו:</p>
                <ul className="space-y-1 text-xs text-gray-600 dark:text-gray-400">
                  {data.ranked_candidates.slice(0, 5).map((c) => (
                    <li key={c.soldier_id} className="flex gap-2">
                      <span className="text-gray-400">•</span>
                      <span>
                        <span className="font-medium">{c.full_name}</span>
                        {c.reason_excluded
                          ? ` — ${c.reason_excluded}`
                          : ` — ניקוד גבוה יותר (${c.score.toFixed(1)})`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/types.py backend/app/routes/assignments.py frontend/src/components/ExplanationModal.tsx
git commit -m "feat: redesigned explanation modal with summary, standing table, rejected candidates"
```
