# Partial Exemptions Column + Exemption-Type Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "פטורים חלקיים" (partial exemptions) column to the potential table showing how many soldiers in each subunit have an active exemption from some (not all) of their eligible duty types, plus a modal — reachable by clicking an exemption name in the soldier detail table — to view (and, with permission, edit) that exemption type.

**Architecture:** The backend already computes, per soldier, which duty types they're eligible for and which active exemptions apply (`compute_potential` in `backend/app/services/potential.py`). We extend that same loop to also flag soldiers who are still counted toward potential but partially exempt, and expose the flag + a subtree-level count through the existing `/potential` route. The frontend adds a column and, in the existing soldier detail sub-table, renders the partial-exemption names as clickable chips that open a new `ExemptionTypeViewModal` (view + permission-gated edit), reusing the existing `duty-config` API functions.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + `@tanstack/react-table` via the existing `DataTable` component, `react-i18next`, Vitest + Testing Library for frontend component tests, pytest for backend tests.

## Global Constraints

- Backend tests: run from `backend/` with venv active — `pytest -q` (fast suite; parallel by default). Do not use `--slow` unless doing a full pre-release pass.
- Frontend: run from `frontend/` — `npm test` (vitest), `npm run lint` (zero warnings enforced), `npm run typecheck` (`tsc --noEmit`, run separately from lint).
- Hebrew UI strings, English code/identifiers.
- Feature branch workflow — commit small, per-task commits. Stay on the current branch (`potential-page-improvements`); do not commit to `master`.
- No new backend endpoints — reuse `listExemptionTypes`, `getAllExemptionDutyTypeMaps`, `listDutyTypes`, `updateExemptionType`, `setExemptionDutyTypes` from `frontend/src/api/dutyConfig.ts`.
- Partial exemptions never change `final_potential` / `raw_eligible_count` — they are informational only.

---

### Task 1: Backend — compute partial-exemption flag per soldier

**Files:**
- Modify: `backend/app/services/potential.py:25-32` (dataclass), `backend/app/services/potential.py:45-53` (dataclass), `backend/app/services/potential.py:161-165` (loop branch)
- Test: `backend/app/services/tests/test_potential.py`

**Interfaces:**
- Produces: `SoldierPotentialDetail.partial_exemption_names: list[str]` (default `[]`), `PotentialResult.partial_exemption_count: int` (default `0`). Later tasks (route layer, frontend) read these two fields by exact name.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_potential.py`. First add the import needed for the new model:

```python
from app.db.models import DutyType, ExemptionDutyTypeMap, ExemptionType, Soldier, SoldierExemption, PotentialModifier
```

(This replaces the existing import line 7, which is missing `ExemptionDutyTypeMap`.)

Then append these two tests at the end of the file:

```python
def test_partial_exemption_flags_soldier_still_counted(app_session):
    node = create_node(app_session, level="team", name="Test Co Partial", parent_id=None)
    app_session.flush()
    dt1 = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    dt2 = DutyType(name="מטבח", score_per_day=Decimal("1.0"), requirements={})
    app_session.add_all([dt1, dt2])
    app_session.flush()
    et = ExemptionType(name="פטור שמירות", is_global=False, is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()
    app_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt1.id))

    s = _make_soldier(app_session, node_id=node.id)
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    detail = result.soldiers[0]
    assert detail.counted is True
    assert detail.partial_exemption_names == ["פטור שמירות"]
    assert result.raw_eligible_count == 1
    assert result.partial_exemption_count == 1


def test_fully_exempt_soldier_not_counted_as_partial(app_session):
    node = create_node(app_session, level="team", name="Test Co Partial 2", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    et = ExemptionType(name="פטור רפואי מלא 2", is_global=True, is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id)
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    detail = result.soldiers[0]
    assert detail.counted is False
    assert detail.partial_exemption_names == []
    assert result.partial_exemption_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`, venv active): `pytest app/services/tests/test_potential.py -v`
Expected: `test_partial_exemption_flags_soldier_still_counted` FAILs with `AttributeError: 'SoldierPotentialDetail' object has no attribute 'partial_exemption_names'` (or similar), `test_fully_exempt_soldier_not_counted_as_partial` FAILs the same way.

- [ ] **Step 3: Add the fields to the dataclasses**

In `backend/app/services/potential.py`, change the `SoldierPotentialDetail` dataclass (currently lines 25-32):

```python
@dataclass
class SoldierPotentialDetail:
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None  # populated when counted is False
    exemption_names: list[str] = field(default_factory=list)  # populated when reason == "exempted"
    rank: str | None = None
    partial_exemption_names: list[str] = field(default_factory=list)  # populated when counted is True but partially exempt
```

Change the `PotentialResult` dataclass (currently lines 45-53):

```python
@dataclass
class PotentialResult:
    node_id: uuid.UUID
    as_of: date
    raw_eligible_count: int
    total_soldiers: int = 0
    modifiers: list[ModifierDetail] = field(default_factory=list)
    final_potential: int = 0
    soldiers: list[SoldierPotentialDetail] = field(default_factory=list)
    partial_exemption_count: int = 0
```

- [ ] **Step 4: Compute the flag in `compute_potential`**

In `backend/app/services/potential.py`, the `remaining` branch of the per-soldier loop currently reads (around line 161-164):

```python
        remaining = base_eligible - excluded
        if remaining:
            details.append(SoldierPotentialDetail(s.id, s.full_name, True, rank=rank))
            raw_count += 1
```

Replace it with:

```python
        remaining = base_eligible - excluded
        if remaining:
            partial_names: list[str] = []
            if excluded & base_eligible:
                partial_names = sorted({
                    regular_types[ex.exemption_type_id].name
                    for ex in active_exemptions
                    if etid_to_dtids.get(ex.exemption_type_id, set()) & base_eligible
                })
            details.append(SoldierPotentialDetail(
                s.id, s.full_name, True, rank=rank, partial_exemption_names=partial_names,
            ))
            raw_count += 1
```

Then, in the `return PotentialResult(...)` statement at the end of `compute_potential` (currently lines 198-206), add the new field:

```python
    return PotentialResult(
        node_id=node_id,
        as_of=reference_date,
        raw_eligible_count=raw_count,
        total_soldiers=total_soldiers,
        modifiers=modifier_details,
        final_potential=raw_count + modifier_sum,
        soldiers=details,
        partial_exemption_count=sum(1 for d in details if d.partial_exemption_names),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest app/services/tests/test_potential.py -v`
Expected: all tests PASS, including the two new ones.

- [ ] **Step 6: Run the full fast backend suite to check for regressions**

Run: `pytest -q`
Expected: all tests pass (no regressions in other modules that construct `SoldierPotentialDetail`/`PotentialResult`, since the new fields are additive with defaults).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/potential.py backend/app/services/tests/test_potential.py
git commit -m "feat: flag soldiers with partial duty-type exemptions in potential calc"
```

---

### Task 2: Backend — expose the new fields through the `/potential` route

**Files:**
- Modify: `backend/app/routes/potential.py:21-27` (`SoldierDetailOut`), `backend/app/routes/potential.py:39-46` (`PotentialOut`), `backend/app/routes/potential.py:49-72` (`_out`)
- Test: `backend/app/services/tests/test_potential_routes.py`

**Interfaces:**
- Consumes: `svc.PotentialResult.partial_exemption_count: int`, `svc.SoldierPotentialDetail.partial_exemption_names: list[str]` (Task 1).
- Produces: JSON response fields `partial_exemption_count: int` and, per soldier, `partial_exemption_names: list[str] | null` (gated by the same `can_view_exemptions` privacy check as the existing `exemption_names` field). Task 5 (frontend) reads these exact JSON keys.

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_potential_routes.py`:

```python
def test_get_potential_includes_partial_exemption_fields(client, admin_session):
    node = create_node(admin_session, level="פלוגה", name="Route Test Partial Co")
    dm = create_soldier(
        admin_session, personal_number="5000903", role="duty_manager", hierarchy_node_id=node.id,
    )
    admin_session.commit()

    resp = client.get(
        "/api/potential",
        params={"node_id": str(node.id), "reference_date": "2026-07-03"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["partial_exemption_count"] == 0
    assert body["soldiers"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/services/tests/test_potential_routes.py::test_get_potential_includes_partial_exemption_fields -v`
Expected: FAIL with a `KeyError` (`'partial_exemption_count'`) or a pydantic validation error, since the response model doesn't have the field yet.

- [ ] **Step 3: Extend the response schemas and `_out`**

In `backend/app/routes/potential.py`, change `SoldierDetailOut` (currently lines 21-27):

```python
class SoldierDetailOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None
    exemption_names: list[str] | None = None
    rank: str | None = None
    partial_exemption_names: list[str] | None = None
```

Change `PotentialOut` (currently lines 39-46):

```python
class PotentialOut(BaseModel):
    node_id: uuid.UUID
    as_of: str
    raw_eligible_count: int
    total_soldiers: int
    modifiers: list[ModifierOut]
    final_potential: int
    soldiers: list[SoldierDetailOut]
    partial_exemption_count: int
```

Change `_out` (currently lines 49-72) to populate both fields:

```python
def _out(r: svc.PotentialResult, *, can_view_exemptions: bool) -> PotentialOut:
    return PotentialOut(
        node_id=r.node_id,
        as_of=r.as_of.isoformat(),
        raw_eligible_count=r.raw_eligible_count,
        total_soldiers=r.total_soldiers,
        modifiers=[
            ModifierOut(
                id=m.id, delta=m.delta, reason=m.reason,
                start_date=m.start_date.isoformat(),
                end_date=m.end_date.isoformat() if m.end_date else None,
                created_by=m.created_by,
            ) for m in r.modifiers
        ],
        final_potential=r.final_potential,
        soldiers=[
            SoldierDetailOut(
                soldier_id=s.soldier_id, full_name=s.full_name, counted=s.counted, reason=s.reason,
                exemption_names=(s.exemption_names or None) if can_view_exemptions else None,
                rank=s.rank,
                partial_exemption_names=(s.partial_exemption_names or None) if can_view_exemptions else None,
            )
            for s in r.soldiers
        ],
        partial_exemption_count=r.partial_exemption_count,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/services/tests/test_potential_routes.py -v`
Expected: all tests in the file PASS, including the new one.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/potential.py backend/app/services/tests/test_potential_routes.py
git commit -m "feat: expose partial-exemption fields on the /potential route"
```

---

### Task 3: Frontend — API types, table column, whole-org aggregate, i18n

**Files:**
- Modify: `frontend/src/api/potential.ts:3-10` (`SoldierPotentialDetail`), `frontend/src/api/potential.ts:21-29` (`PotentialResult`)
- Modify: `frontend/src/pages/planning/PotentialPage.tsx:44-57` (`wholeOrgResult`), `frontend/src/pages/planning/PotentialPage.tsx:178-192` (`cols` array)
- Modify: `frontend/src/i18n/he.json:581` (insert after `eligible_tooltip`)

**Interfaces:**
- Consumes: JSON fields `partial_exemption_count` and `partial_exemption_names` from Task 2.
- Produces: `SoldierPotentialDetail.partial_exemption_names: string[] | null`, `PotentialResult.partial_exemption_count: number` — Task 5 reads these exact names when rendering chips.

- [ ] **Step 1: Add the fields to the TypeScript API types**

In `frontend/src/api/potential.ts`, change `SoldierPotentialDetail` (currently lines 3-10):

```typescript
export interface SoldierPotentialDetail {
  soldier_id: string;
  full_name: string;
  counted: boolean;
  reason: string | null;
  exemption_names: string[] | null;
  rank: string | null;
  partial_exemption_names: string[] | null;
}
```

Change `PotentialResult` (currently lines 21-29):

```typescript
export interface PotentialResult {
  node_id: string;
  as_of: string;
  raw_eligible_count: number;
  total_soldiers: number;
  modifiers: PotentialModifierDTO[];
  final_potential: number;
  soldiers: SoldierPotentialDetail[];
  partial_exemption_count: number;
}
```

- [ ] **Step 2: Fix the whole-org synthetic aggregate**

In `frontend/src/pages/planning/PotentialPage.tsx`, the `wholeOrgResult` object literal (currently lines 44-57) constructs a `PotentialResult` manually and must include the new required field:

```typescript
  const wholeOrgResult = useMemo((): PotentialResult | null => {
    if (topLevelRoots.length === 0) return null;
    const rootResults = topLevelRoots.map((n) => results[n.id]).filter((r): r is PotentialResult => !!r);
    if (rootResults.length !== topLevelRoots.length) return null; // not all roots loaded yet
    return {
      node_id: WHOLE_ORG_ID,
      as_of: rootResults[0].as_of,
      raw_eligible_count: rootResults.reduce((s, r) => s + r.raw_eligible_count, 0),
      total_soldiers: rootResults.reduce((s, r) => s + r.total_soldiers, 0),
      modifiers: rootResults.flatMap((r) => r.modifiers),
      final_potential: rootResults.reduce((s, r) => s + r.final_potential, 0),
      soldiers: rootResults.flatMap((r) => r.soldiers),
      partial_exemption_count: rootResults.reduce((s, r) => s + r.partial_exemption_count, 0),
    };
  }, [topLevelRoots, results]);
```

- [ ] **Step 3: Add i18n keys**

In `frontend/src/i18n/he.json`, inside the `"potential"` block, immediately after the `eligible_tooltip` line (currently line 583), insert:

```json
    "partial_exemptions": "פטורים חלקיים",
    "partial_exemptions_tooltip": "מספר החיילים ביחידה זו ובכל תתי-היחידות שלה שיש להם פטור פעיל מסוג תורנות אחד או יותר, אך הם עדיין כשירים לפחות לסוג תורנות אחר — ולכן ממשיכים להיספר בפוטנציאל של תת-היחידה שלהם.",
```

- [ ] **Step 4: Add the column**

In `frontend/src/pages/planning/PotentialPage.tsx`, the `cols` array currently has `eligible` immediately followed by `pct_eligible` (lines 185-202). Insert a new column between them:

```typescript
    {
      id: "eligible",
      header: t("potential.eligible"),
      headerTooltip: t("potential.eligible_tooltip"),
      cell: (n) => displayResults[n.id]?.raw_eligible_count ?? "-",
      sortValue: (n) => displayResults[n.id]?.raw_eligible_count ?? -1,
    },
    {
      id: "partial_exemptions",
      header: t("potential.partial_exemptions"),
      headerTooltip: t("potential.partial_exemptions_tooltip"),
      cell: (n) => displayResults[n.id]?.partial_exemption_count ?? "-",
      sortValue: (n) => displayResults[n.id]?.partial_exemption_count ?? -1,
    },
    {
      id: "pct_eligible",
      header: t("potential.pct_eligible"),
      ...
```

(Only the new `partial_exemptions` block is added; `eligible` and `pct_eligible` are unchanged and shown here for placement context.)

- [ ] **Step 5: Verify with typecheck and lint**

Run (from `frontend/`): `npm run typecheck`
Expected: no errors.

Run: `npm run lint`
Expected: no errors/warnings.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/potential.ts frontend/src/pages/planning/PotentialPage.tsx frontend/src/i18n/he.json
git commit -m "feat: add partial-exemptions column to potential table"
```

---

### Task 4: Frontend — `ExemptionTypeViewModal` component (view + permission-gated edit)

**Files:**
- Create: `frontend/src/components/ExemptionTypeViewModal.tsx`
- Test: `frontend/src/components/ExemptionTypeViewModal.test.tsx`

**Interfaces:**
- Consumes: `ExemptionType` and `DutyType` types, `updateExemptionType(id, input)` and `setExemptionDutyTypes(id, duty_type_ids)` from `frontend/src/api/dutyConfig.ts` (all pre-existing, unchanged).
- Produces: default export `ExemptionTypeViewModal` React component with props `{ exemptionType: ExemptionType; mappedDutyTypeIds: string[]; dutyTypes: DutyType[]; canEdit: boolean; onClose: () => void; onSaved: (updated: ExemptionType, mappedDutyTypeIds: string[]) => void }`. Task 5 renders this component and supplies these exact props.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/ExemptionTypeViewModal.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ExemptionTypeViewModal from "./ExemptionTypeViewModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

const mockUpdateExemptionType = vi.fn(() =>
  Promise.resolve({ id: "e1", name: "פטור שמירות", description: null, is_global: false, is_medical: false, is_commander_exemption: false })
);
const mockSetExemptionDutyTypes = vi.fn(() => Promise.resolve(["d1", "d2"]));

vi.mock("../api/dutyConfig", () => ({
  updateExemptionType: (...args: unknown[]) => mockUpdateExemptionType(...args),
  setExemptionDutyTypes: (...args: unknown[]) => mockSetExemptionDutyTypes(...args),
}));

const exemptionType = {
  id: "e1", name: "פטור שמירות", description: null,
  is_global: false, is_medical: false, is_commander_exemption: false,
};
const dutyTypes = [
  { id: "d1", name: "שמירה", score_per_day: "1.0", description: null, active: true, contact_name: null, contact_phone: null, start_time: null, end_time: null, instructions: null, is_external: false, eligible_node_ids: null },
  { id: "d2", name: "מטבח", score_per_day: "1.0", description: null, active: true, contact_name: null, contact_phone: null, start_time: null, end_time: null, instructions: null, is_external: false, eligible_node_ids: null },
];

test("view mode shows the mapped duty type name and hides the pencil when canEdit is false", () => {
  render(
    <ExemptionTypeViewModal
      exemptionType={exemptionType}
      mappedDutyTypeIds={["d1"]}
      dutyTypes={dutyTypes}
      canEdit={false}
      onClose={() => {}}
      onSaved={() => {}}
    />
  );
  expect(screen.getByText("שמירה")).toBeInTheDocument();
  expect(screen.queryByTestId("exemption-edit-pencil")).not.toBeInTheDocument();
});

test("pencil is shown when canEdit is true, and clicking it reveals the edit form", () => {
  render(
    <ExemptionTypeViewModal
      exemptionType={exemptionType}
      mappedDutyTypeIds={["d1"]}
      dutyTypes={dutyTypes}
      canEdit={true}
      onClose={() => {}}
      onSaved={() => {}}
    />
  );
  fireEvent.click(screen.getByTestId("exemption-edit-pencil"));
  expect(screen.getByTestId("exemption-edit-global")).toBeInTheDocument();
});

test("saving edits calls updateExemptionType and setExemptionDutyTypes, then returns to view mode", async () => {
  const onSaved = vi.fn();
  render(
    <ExemptionTypeViewModal
      exemptionType={exemptionType}
      mappedDutyTypeIds={["d1"]}
      dutyTypes={dutyTypes}
      canEdit={true}
      onClose={() => {}}
      onSaved={onSaved}
    />
  );
  fireEvent.click(screen.getByTestId("exemption-edit-pencil"));
  fireEvent.click(screen.getByTestId("exemption-edit-dt-מטבח"));
  fireEvent.click(screen.getByTestId("exemption-edit-save"));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(mockUpdateExemptionType).toHaveBeenCalledWith("e1", {
    name: "פטור שמירות", is_global: false, is_medical: false, is_commander_exemption: false,
  });
  expect(mockSetExemptionDutyTypes).toHaveBeenCalledWith("e1", ["d1", "d2"]);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm test -- ExemptionTypeViewModal`
Expected: FAIL — the module `./ExemptionTypeViewModal` does not exist yet.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/ExemptionTypeViewModal.tsx`:

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyType, ExemptionType, setExemptionDutyTypes, updateExemptionType } from "../api/dutyConfig";

interface Props {
  exemptionType: ExemptionType;
  mappedDutyTypeIds: string[];
  dutyTypes: DutyType[];
  canEdit: boolean;
  onClose: () => void;
  onSaved: (updated: ExemptionType, mappedDutyTypeIds: string[]) => void;
}

export default function ExemptionTypeViewModal({
  exemptionType, mappedDutyTypeIds, dutyTypes, canEdit, onClose, onSaved,
}: Props) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(exemptionType.name);
  const [isGlobal, setIsGlobal] = useState(exemptionType.is_global ?? false);
  const [isMedical, setIsMedical] = useState(exemptionType.is_medical ?? false);
  const [isCommander, setIsCommander] = useState(exemptionType.is_commander_exemption ?? false);
  const [selectedDutyTypeIds, setSelectedDutyTypeIds] = useState<string[]>(mappedDutyTypeIds);
  const [saving, setSaving] = useState(false);

  const mappedNames = dutyTypes.filter((d) => mappedDutyTypeIds.includes(d.id)).map((d) => d.name);

  function toggleDutyType(id: string) {
    setSelectedDutyTypeIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await updateExemptionType(exemptionType.id, {
        name, is_global: isGlobal, is_medical: isMedical, is_commander_exemption: isCommander,
      });
      const newMapping = isGlobal ? [] : await setExemptionDutyTypes(exemptionType.id, selectedDutyTypeIds);
      onSaved(updated, newMapping);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4"
      onClick={onClose}
      data-testid="exemption-type-view-modal"
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-base flex items-center gap-2">
            {editing ? (
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="border border-gray-300 dark:border-gray-600 rounded p-1 text-sm dark:bg-gray-700 dark:text-gray-100"
                data-testid="exemption-name-input"
              />
            ) : (
              <span>{exemptionType.name}</span>
            )}
            {canEdit && !editing && (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="text-gray-400 hover:text-indigo-600"
                aria-label={t("duty_config.edit", "ערוך")}
                data-testid="exemption-edit-pencil"
              >
                ✏️
              </button>
            )}
          </h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        {!editing && (
          <div className="space-y-3 text-sm">
            <div className="flex gap-2 flex-wrap">
              {exemptionType.is_global && (
                <span className="text-xs bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 px-2 py-0.5 rounded">
                  {t("duty_config.global")}
                </span>
              )}
              {exemptionType.is_medical && (
                <span className="text-xs bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 px-2 py-0.5 rounded">
                  🏥 {t("duty_config.medical")}
                </span>
              )}
              {exemptionType.is_commander_exemption && (
                <span className="text-xs bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 px-2 py-0.5 rounded">
                  🎖️ {t("duty_config.commander_exemption")}
                </span>
              )}
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{t("duty_config.exempts_from")}:</p>
              {exemptionType.is_global ? (
                <p className="text-gray-700 dark:text-gray-300">{t("duty_config.global_exempt_desc")}</p>
              ) : mappedNames.length > 0 ? (
                <p className="text-gray-700 dark:text-gray-300">{mappedNames.join(", ")}</p>
              ) : (
                <p className="text-gray-400 dark:text-gray-500">—</p>
              )}
            </div>
          </div>
        )}

        {editing && (
          <div className="space-y-3 text-sm">
            <div className="flex gap-4 flex-wrap">
              <label className="flex items-center gap-1 text-xs cursor-pointer">
                <input type="checkbox" checked={isGlobal} onChange={(e) => setIsGlobal(e.target.checked)} data-testid="exemption-edit-global" />
                {t("duty_config.global")}
              </label>
              <label className="flex items-center gap-1 text-xs cursor-pointer">
                <input type="checkbox" checked={isMedical} onChange={(e) => setIsMedical(e.target.checked)} data-testid="exemption-edit-medical" />
                🏥 {t("duty_config.medical")}
              </label>
              <label className="flex items-center gap-1 text-xs cursor-pointer">
                <input type="checkbox" checked={isCommander} onChange={(e) => setIsCommander(e.target.checked)} data-testid="exemption-edit-commander" />
                🎖️ {t("duty_config.commander_exemption")}
              </label>
            </div>
            {!isGlobal && (
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{t("duty_config.exempts_from")}:</p>
                <div className="flex flex-wrap gap-2">
                  {dutyTypes.map((d) => (
                    <label key={d.id} className="text-xs flex items-center gap-1">
                      <input
                        type="checkbox"
                        checked={selectedDutyTypeIds.includes(d.id)}
                        onChange={() => toggleDutyType(d.id)}
                        data-testid={`exemption-edit-dt-${d.name}`}
                      />
                      {d.name}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setEditing(false)}
                disabled={saving}
                className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50"
              >
                {t("duty_config.cancel", "ביטול")}
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
                data-testid="exemption-edit-save"
              >
                {saving ? "..." : t("duty_config.save", "שמור")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Add the `commander_exemption` i18n key**

In `frontend/src/i18n/he.json`, inside the `"duty_config"` block, immediately after the `"medical"` line (currently line 143), insert:

```json
    "commander_exemption": "פטור פיקודי",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- ExemptionTypeViewModal`
Expected: all 3 tests PASS.

- [ ] **Step 6: Typecheck and lint**

Run: `npm run typecheck` — expect no errors.
Run: `npm run lint` — expect no errors/warnings.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ExemptionTypeViewModal.tsx frontend/src/components/ExemptionTypeViewModal.test.tsx frontend/src/i18n/he.json
git commit -m "feat: add ExemptionTypeViewModal component with permission-gated edit"
```

---

### Task 5: Frontend — wire clickable exemption chips into the potential page

**Files:**
- Modify: `frontend/src/pages/planning/PotentialPage.tsx`

**Interfaces:**
- Consumes: `ExemptionTypeViewModal` (Task 4), `listExemptionTypes()`, `getAllExemptionDutyTypeMaps()`, `listDutyTypes()`, `ExemptionType`, `DutyType` from `frontend/src/api/dutyConfig.ts`, `useAuth()` from `frontend/src/auth/AuthContext.tsx`.

- [ ] **Step 1: Add imports and state**

In `frontend/src/pages/planning/PotentialPage.tsx`, add to the top-of-file imports (after the existing `fetchFullTree` import block):

```typescript
import { useAuth } from "../../auth/AuthContext";
import ExemptionTypeViewModal from "../../components/ExemptionTypeViewModal";
import {
  DutyType,
  ExemptionType,
  getAllExemptionDutyTypeMaps,
  listDutyTypes,
  listExemptionTypes,
} from "../../api/dutyConfig";
```

Inside the `PotentialPage` component, after the existing `const [exportRows, setExportRows] = useState<NodeDTO[]>([]);` line, add:

```typescript
  const { user } = useAuth();
  const canEditExemptions = user?.role === "admin" || !!user?.is_duty_manager;
  const [exemptionTypes, setExemptionTypes] = useState<ExemptionType[]>([]);
  const [exemptionDutyMap, setExemptionDutyMap] = useState<Record<string, string[]>>({});
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [viewingExemption, setViewingExemption] = useState<ExemptionType | null>(null);
```

- [ ] **Step 2: Load exemption/duty-type lookups once**

Add a new `useEffect` next to the existing `fetchFullTree` effect:

```typescript
  useEffect(() => {
    Promise.all([listExemptionTypes(), getAllExemptionDutyTypeMaps(), listDutyTypes()]).then(
      ([ets, map, dts]) => {
        setExemptionTypes(ets);
        setExemptionDutyMap(map);
        setDutyTypes(dts);
      },
    );
  }, []);
```

- [ ] **Step 3: Add the chip-click handler**

Add a helper function next to `reasonText`:

```typescript
  function openExemptionModal(name: string) {
    const et = exemptionTypes.find((e) => e.name === name);
    if (et) setViewingExemption(et);
  }
```

- [ ] **Step 4: Render partial-exemption names as clickable chips**

In the `soldierCols` array, replace the `reason` column's `cell` (currently `cell: (s) => (s.counted ? "—" : reasonText(s)),`) with:

```typescript
    {
      id: "reason",
      header: t("potential.reason_col"),
      cell: (s) => {
        if (s.counted) {
          if (!s.partial_exemption_names || s.partial_exemption_names.length === 0) return "—";
          return (
            <span className="flex flex-wrap gap-1">
              {s.partial_exemption_names.map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => openExemptionModal(name)}
                  className="text-xs text-blue-600 dark:text-blue-400 underline"
                >
                  {name}
                </button>
              ))}
            </span>
          );
        }
        return reasonText(s);
      },
      filterValue: (s) => reasonText(s),
    },
```

Update `reasonText` (currently the function above `cols`) to also handle the counted+partial case, so filtering/search still works:

```typescript
  function reasonText(s: SoldierPotentialDetail): string {
    if (s.counted) {
      return s.partial_exemption_names && s.partial_exemption_names.length > 0
        ? s.partial_exemption_names.join(", ")
        : "";
    }
    if (s.reason === "exempted") {
      return s.exemption_names && s.exemption_names.length > 0
        ? s.exemption_names.join(", ")
        : t("potential.reason_exempted_restricted");
    }
    return reasonLabel(s.reason);
  }
```

- [ ] **Step 5: Render the modal**

At the end of the JSX returned by `PotentialPage`, immediately before the closing `</Layout>`, add:

```tsx
        {viewingExemption && (
          <ExemptionTypeViewModal
            exemptionType={viewingExemption}
            mappedDutyTypeIds={exemptionDutyMap[viewingExemption.id] ?? []}
            dutyTypes={dutyTypes}
            canEdit={canEditExemptions}
            onClose={() => setViewingExemption(null)}
            onSaved={(updated, mappedIds) => {
              setExemptionTypes((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
              setExemptionDutyMap((prev) => ({ ...prev, [updated.id]: mappedIds }));
              setViewingExemption(updated);
            }}
          />
        )}
```

- [ ] **Step 6: Typecheck and lint**

Run (from `frontend/`): `npm run typecheck` — expect no errors.
Run: `npm run lint` — expect no errors/warnings.

- [ ] **Step 7: Manual verification in the browser**

Start the dev stack (`.\dev.ps1` from repo root), open `http://localhost:5173`, sign in as an admin or duty manager, navigate to the potential page:
- Confirm the "פטורים חלקיים" column appears after "כשירים" with a "?" that opens a tooltip modal.
- Give a soldier a non-global exemption type mapped to only one of their eligible duty types, confirm they still show as "נספר" (counted) and the subunit's partial-exemptions count increments.
- Expand that subunit's row, confirm the exemption name renders as a clickable chip in the "סיבה" column.
- Click the chip, confirm the view modal opens with the correct badges and duty-type summary.
- As admin/duty-manager, confirm the pencil icon appears and editing + saving updates the modal and persists (reopen to confirm).
- Log in as a plain soldier/commander (no duty-manager scope), confirm the pencil icon does not appear.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/planning/PotentialPage.tsx
git commit -m "feat: wire clickable exemption chips to the exemption-type view modal"
```

---

## Self-Review Notes

- **Spec coverage:** partial-exemption count/column (Task 1, 3), soldier-still-counted semantics preserved (Task 1 tests), tooltip modal via existing `headerTooltip` mechanism (Task 3), clickable exemption chips (Task 5), view+edit modal with permission gate (Task 4), reuse of existing duty-config API (Task 4/5), tests for backend and the new component (Tasks 1, 2, 4) — all covered.
- **Placeholder scan:** no TBD/TODO; all steps contain complete code.
- **Type consistency:** `partial_exemption_names` / `partial_exemption_count` spelled identically across backend dataclasses, backend response schema, and frontend TS interfaces. `ExemptionTypeViewModal` prop names (`exemptionType`, `mappedDutyTypeIds`, `dutyTypes`, `canEdit`, `onClose`, `onSaved`) match between Task 4's implementation/tests and Task 5's usage.
