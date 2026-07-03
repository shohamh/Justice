# Potential Page Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make soldier names in the Potential page's expanded detail table clickable (opening the existing soldier modal) with a rank column, and make the main per-node table easier to read (hierarchy indentation + level badge, explanatory tooltips, and a "% of parent" column).

**Architecture:** All changes are additive edits to the existing `PotentialPage.tsx` single-page component (matches this codebase's convention of large single-file pages, e.g. `TransparencyPage.tsx`), plus a small, non-breaking backend field addition (`rank`) threaded through the existing `compute_potential` → route → frontend API type chain. No new files, no new endpoints, no schema/migration changes.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + react-i18next + `@tanstack/react-table` via the existing `DataTable` component (frontend), pytest (backend tests).

## Global Constraints

- Hebrew UI, English code (per project CLAUDE.md) — all user-facing strings go through `frontend/src/i18n/he.json` and `t()`.
- Follow `backend\.venv\Scripts\activate` then run pytest for backend; run `npm run typecheck` for frontend (from `frontend/`) — per project CLAUDE.md one-liners.
- Only run targeted tests for this feature, not the full suite, per this project's established workflow.
- Never commit directly to `master` — this work should happen on a feature branch (create one if not already on one before Task 1).
- Design doc: `docs/superpowers/specs/2026-07-03-potential-page-improvements-design.md` — refer back to it if anything here seems ambiguous.

---

### Task 1: Backend — add `rank` to soldier potential detail

**Files:**
- Modify: `backend/app/services/potential.py:25-31` (dataclass), `:142-170` (compute_potential loop)
- Modify: `backend/app/routes/potential.py:21-26` (SoldierDetailOut), `:61-67` (`_out`)
- Test: `backend/app/services/tests/test_potential.py`

**Interfaces:**
- Consumes: existing `_rank_as_of(soldier: Soldier, reference_date: date) -> str | None` (already defined at `backend/app/services/potential.py:54-67`, unchanged).
- Produces: `SoldierPotentialDetail.rank: str | None` (service dataclass) and `SoldierDetailOut.rank: str | None` (route response model) — later frontend tasks read this field as `rank` on the JSON soldier object.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_potential.py` (after `test_compute_potential_counts_eligible_soldiers`, before `test_regular_exemption_excludes_soldier_and_names_it`):

```python
def test_soldier_detail_includes_rank(app_session):
    node = create_node(app_session, level="team", name="Test Co Rank", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    _make_soldier(app_session, node_id=node.id, rank="סמל")
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.soldiers[0].rank == "סמל"


def test_soldier_detail_rank_reflects_next_rank_date_rollover(app_session):
    node = create_node(app_session, level="team", name="Test Co Rank 2", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id, rank="טוראי")
    s.next_rank_date = date(2026, 1, 1)  # before reference_date -> rolled over
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.soldiers[0].rank == "רבט"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`, with `.venv` active): `pytest app/services/tests/test_potential.py -k rank -v`
Expected: FAIL — `AttributeError: 'SoldierPotentialDetail' object has no attribute 'rank'`

- [ ] **Step 3: Add the `rank` field to the dataclass**

In `backend/app/services/potential.py`, change:

```python
@dataclass
class SoldierPotentialDetail:
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None  # populated when counted is False
    exemption_names: list[str] = field(default_factory=list)  # populated when reason == "exempted"
```

to:

```python
@dataclass
class SoldierPotentialDetail:
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None  # populated when counted is False
    exemption_names: list[str] = field(default_factory=list)  # populated when reason == "exempted"
    rank: str | None = None
```

- [ ] **Step 4: Thread `rank` through `compute_potential`**

In `backend/app/services/potential.py`, change the loop body (currently lines 142-170):

```python
    details: list[SoldierPotentialDetail] = []
    raw_count = 0
    for s in subtree_soldiers:
        if s.left_at is not None and s.left_at <= reference_date:
            details.append(SoldierPotentialDetail(s.id, s.full_name, False, "discharged as of reference date"))
            continue
        rank = _rank_as_of(s, reference_date)
        base_eligible = _base_eligible_duty_types(s, rank, duty_types, reference_date)
        active_exemptions = [
            ex for ex in exemptions_by_soldier.get(s.id, [])
            if ex.start_date <= reference_date and (ex.end_date is None or ex.end_date >= reference_date)
        ]
        excluded: set[uuid.UUID] = set()
        for ex in active_exemptions:
            excluded |= etid_to_dtids.get(ex.exemption_type_id, set())
        remaining = base_eligible - excluded
        if remaining:
            details.append(SoldierPotentialDetail(s.id, s.full_name, True))
            raw_count += 1
        elif base_eligible:
            # would have been eligible, but active exemptions excluded every remaining duty type
            names = sorted({
                regular_types[ex.exemption_type_id].name
                for ex in active_exemptions
                if etid_to_dtids.get(ex.exemption_type_id, set()) & base_eligible
            })
            details.append(SoldierPotentialDetail(s.id, s.full_name, False, "exempted", names))
        else:
            details.append(SoldierPotentialDetail(s.id, s.full_name, False, "no_eligible_duty_types"))
```

to:

```python
    details: list[SoldierPotentialDetail] = []
    raw_count = 0
    for s in subtree_soldiers:
        rank = _rank_as_of(s, reference_date)
        if s.left_at is not None and s.left_at <= reference_date:
            details.append(SoldierPotentialDetail(
                s.id, s.full_name, False, "discharged as of reference date", rank=rank,
            ))
            continue
        base_eligible = _base_eligible_duty_types(s, rank, duty_types, reference_date)
        active_exemptions = [
            ex for ex in exemptions_by_soldier.get(s.id, [])
            if ex.start_date <= reference_date and (ex.end_date is None or ex.end_date >= reference_date)
        ]
        excluded: set[uuid.UUID] = set()
        for ex in active_exemptions:
            excluded |= etid_to_dtids.get(ex.exemption_type_id, set())
        remaining = base_eligible - excluded
        if remaining:
            details.append(SoldierPotentialDetail(s.id, s.full_name, True, rank=rank))
            raw_count += 1
        elif base_eligible:
            # would have been eligible, but active exemptions excluded every remaining duty type
            names = sorted({
                regular_types[ex.exemption_type_id].name
                for ex in active_exemptions
                if etid_to_dtids.get(ex.exemption_type_id, set()) & base_eligible
            })
            details.append(SoldierPotentialDetail(s.id, s.full_name, False, "exempted", names, rank=rank))
        else:
            details.append(SoldierPotentialDetail(
                s.id, s.full_name, False, "no_eligible_duty_types", rank=rank,
            ))
```

Note `rank = _rank_as_of(s, reference_date)` moved above the discharged-soldier early-continue, so discharged soldiers still get a rank in the response.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest app/services/tests/test_potential.py -v`
Expected: all pass (15 tests: 13 existing + 2 new)

- [ ] **Step 6: Expose `rank` on the API response model**

In `backend/app/routes/potential.py`, change:

```python
class SoldierDetailOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None
    exemption_names: list[str] | None = None
```

to:

```python
class SoldierDetailOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None
    exemption_names: list[str] | None = None
    rank: str | None = None
```

Then in the same file's `_out` function, change:

```python
        soldiers=[
            SoldierDetailOut(
                soldier_id=s.soldier_id, full_name=s.full_name, counted=s.counted, reason=s.reason,
                exemption_names=(s.exemption_names or None) if can_view_exemptions else None,
            )
            for s in r.soldiers
        ],
```

to:

```python
        soldiers=[
            SoldierDetailOut(
                soldier_id=s.soldier_id, full_name=s.full_name, counted=s.counted, reason=s.reason,
                exemption_names=(s.exemption_names or None) if can_view_exemptions else None,
                rank=s.rank,
            )
            for s in r.soldiers
        ],
```

`rank` is not gated by `can_view_exemptions` or any other permission check — it's not in `PRIVATE_FIELD_NAMES` (`backend/app/auth/authz.py:12`, which only lists `gender`, `phone`, `email`).

- [ ] **Step 7: Run the full potential test suite once more**

Run: `pytest app/services/tests/test_potential.py -v`
Expected: PASS (15/15)

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/potential.py backend/app/routes/potential.py backend/app/services/tests/test_potential.py
git commit -m "feat: expose soldier rank in potential detail"
```

---

### Task 2: Frontend — clickable soldier names + rank column in the detail table

**Files:**
- Modify: `frontend/src/api/potential.ts:3-8` (`SoldierPotentialDetail` interface)
- Modify: `frontend/src/pages/planning/PotentialPage.tsx` (imports + `soldierCols`)
- Modify: `frontend/src/i18n/he.json` (`potential` namespace)

**Interfaces:**
- Consumes: `SoldierLink` component (`frontend/src/components/SoldierLink.tsx`), signature `SoldierLink({ id, name, className? }: { id: string; name: string; className?: string })` — already exists, no changes needed. Consumes backend field `rank: string | null` added in Task 1 (this task assumes Task 1 is deployed/merged so the API actually returns it; if run against an older backend, `rank` will just be `undefined` at runtime and render as `—`, which is harmless).
- Produces: no new exports — this task only changes column definitions inside `PotentialPage.tsx`.

- [ ] **Step 1: Add `rank` to the frontend API type**

In `frontend/src/api/potential.ts`, change:

```typescript
export interface SoldierPotentialDetail {
  soldier_id: string;
  full_name: string;
  counted: boolean;
  reason: string | null;
  exemption_names: string[] | null;
}
```

to:

```typescript
export interface SoldierPotentialDetail {
  soldier_id: string;
  full_name: string;
  counted: boolean;
  reason: string | null;
  exemption_names: string[] | null;
  rank: string | null;
}
```

- [ ] **Step 2: Add the `rank_col` translation key**

In `frontend/src/i18n/he.json`, inside the `"potential"` object, change:

```json
    "soldier_name": "שם חייל",
    "counted_col": "נספר?",
```

to:

```json
    "soldier_name": "שם חייל",
    "rank_col": "דרגה",
    "counted_col": "נספר?",
```

- [ ] **Step 3: Import `SoldierLink` in `PotentialPage.tsx`**

In `frontend/src/pages/planning/PotentialPage.tsx`, change:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, X } from "lucide-react";
import Layout from "../../components/Layout";
import { DataTable, type ColDef } from "../../components/DataTable";
import { ExcelExportButton } from "../../components/ExcelExportButton";
```

to:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, X } from "lucide-react";
import Layout from "../../components/Layout";
import { DataTable, type ColDef } from "../../components/DataTable";
import { ExcelExportButton } from "../../components/ExcelExportButton";
import SoldierLink from "../../components/SoldierLink";
```

- [ ] **Step 4: Make the name cell clickable and add the rank column**

In the same file, change the `soldierCols` name entry and insert a rank column right after it:

```tsx
  const soldierCols: ColDef<SoldierPotentialDetail>[] = [
    {
      id: "name",
      header: t("potential.soldier_name"),
      cell: (s) => s.full_name,
      sortValue: (s) => s.full_name,
      filterValue: (s) => s.full_name,
    },
    {
      id: "counted",
```

to:

```tsx
  const soldierCols: ColDef<SoldierPotentialDetail>[] = [
    {
      id: "name",
      header: t("potential.soldier_name"),
      cell: (s) => <SoldierLink id={s.soldier_id} name={s.full_name} />,
      sortValue: (s) => s.full_name,
      filterValue: (s) => s.full_name,
    },
    {
      id: "rank",
      header: t("potential.rank_col"),
      cell: (s) => s.rank ?? "—",
      sortValue: (s) => s.rank ?? "",
      filterValue: (s) => s.rank ?? "",
    },
    {
      id: "counted",
```

- [ ] **Step 5: Run typecheck**

Run (from `frontend/`): `npm run typecheck`
Expected: no errors

- [ ] **Step 6: Manual verification in the running app**

Using the preview tooling (per this project's established verification workflow): start/reuse the dev stack, log in, navigate to `/planning/potential`, expand any node with soldiers, and confirm:
- soldier names render as clickable indigo links (the existing style from `SoldierLink`) and clicking one opens the soldier modal
- a "דרגה" column appears between name and "נספר?" showing each soldier's rank (or "—")

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/potential.ts frontend/src/pages/planning/PotentialPage.tsx frontend/src/i18n/he.json
git commit -m "feat: clickable soldier names and rank column in potential detail table"
```

---

### Task 3: Frontend — main table hierarchy display, column tooltips, and %-of-parent

**Files:**
- Modify: `frontend/src/pages/planning/PotentialPage.tsx` (imports + `cols`)
- Modify: `frontend/src/i18n/he.json` (`potential` namespace)

**Interfaces:**
- Consumes: `useLevelTypes()` hook (`frontend/src/hooks/useLevelTypes.ts`), returns `{ levelTypes: LevelTypeDTO[], loading: boolean, refresh: () => Promise<void> }` where `LevelTypeDTO = { id: string; key: string; label: string; rank: number }` — already exists, no changes needed. Consumes `NodeDTO.path_ids: string[]` (`frontend/src/api/hierarchy.ts:16`) — root-first array of ancestor ids ending with the node's own id (confirmed via `backend/app/services/hierarchy.py:49`, `node.path_ids = [*parent.path_ids, node.id]`), so `path_ids.length - 1` is the node's depth (0 for roots). Consumes `results: Record<string, PotentialResult>` (already in this file) and `NodeDTO.parent_id: string | null`.
- Produces: no new exports — this task only changes column definitions inside `PotentialPage.tsx`.

- [ ] **Step 1: Add the new translation keys**

In `frontend/src/i18n/he.json`, inside the `"potential"` object, change:

```json
    "eligible": "כשירים",
    "modifiers": "התאמות",
    "final_potential": "פוטנציאל סופי",
```

to:

```json
    "eligible": "כשירים",
    "eligible_tooltip": "מספר החיילים הכשירים לתורנות כלשהי ביחידה זו ובכל תתי-היחידות שלה, נכון לתאריך הייחוס.",
    "modifiers": "התאמות",
    "modifiers_tooltip": "סכום ההתאמות הידניות הפעילות שהוגדרו ליחידה זו ולתתי-היחידות שלה.",
    "final_potential": "פוטנציאל סופי",
    "final_potential_tooltip": "כשירים + התאמות — האומדן הסופי לכמות התורנויות שהיחידה יכולה לספק.",
    "pct_of_parent": "% מהיחידה האם",
    "pct_of_parent_tooltip": "הפוטנציאל הסופי של יחידה זו כאחוז מהפוטנציאל הסופי של היחידה האם הישירה שלה.",
```

- [ ] **Step 2: Import `useLevelTypes`**

In `frontend/src/pages/planning/PotentialPage.tsx`, change:

```tsx
import { fetchFullTree, NodeDTO } from "../../api/hierarchy";
```

to:

```tsx
import { fetchFullTree, NodeDTO } from "../../api/hierarchy";
import { useLevelTypes } from "../../hooks/useLevelTypes";
```

- [ ] **Step 3: Compute the level-label lookup**

In the component body, change:

```tsx
export default function PotentialPage() {
  const { t } = useTranslation();
  const [treeNodes, setTreeNodes] = useState<NodeDTO[]>([]);
```

to:

```tsx
export default function PotentialPage() {
  const { t } = useTranslation();
  const { levelTypes } = useLevelTypes();
  const levelLabelByKey = useMemo(
    () => new Map(levelTypes.map((lt) => [lt.key, lt.label])),
    [levelTypes],
  );
  const [treeNodes, setTreeNodes] = useState<NodeDTO[]>([]);
```

- [ ] **Step 4: Add percentage-of-parent helpers**

Right after the existing `modifierSum` function, add:

```tsx
  function pctOfParentValue(n: NodeDTO): number | null {
    if (!n.parent_id) return null;
    const parentFinal = results[n.parent_id]?.final_potential;
    const ownFinal = results[n.id]?.final_potential;
    if (parentFinal === undefined || ownFinal === undefined || parentFinal === 0) return null;
    return (ownFinal / parentFinal) * 100;
  }

  function pctOfParentText(n: NodeDTO): string {
    const pct = pctOfParentValue(n);
    return pct === null ? "—" : `${pct.toFixed(0)}%`;
  }
```

(Place it directly below the existing:
```tsx
  function modifierSum(r: PotentialResult | undefined): number {
    return r ? r.modifiers.reduce((s, m) => s + m.delta, 0) : 0;
  }
```
)

- [ ] **Step 5: Update `cols` — name cell (indent + level badge), header tooltips, and the new percentage column**

Change:

```tsx
  const cols: ColDef<NodeDTO>[] = [
    {
      id: "name",
      header: t("potential.node"),
      cell: (n) => n.name,
      sortValue: (n) => n.name,
      filterValue: (n) => n.name,
    },
    {
      id: "eligible",
      header: t("potential.eligible"),
      cell: (n) => results[n.id]?.raw_eligible_count ?? "-",
      sortValue: (n) => results[n.id]?.raw_eligible_count ?? -1,
    },
    {
      id: "modifiers",
      header: t("potential.modifiers"),
      cell: (n) => (results[n.id] ? modifierSum(results[n.id]) : "-"),
      sortValue: (n) => (results[n.id] ? modifierSum(results[n.id]) : -Infinity),
    },
    {
      id: "final_potential",
      header: t("potential.final_potential"),
      cell: (n) => results[n.id]?.final_potential ?? "-",
      sortValue: (n) => results[n.id]?.final_potential ?? -1,
    },
  ];
```

to:

```tsx
  const cols: ColDef<NodeDTO>[] = [
    {
      id: "name",
      header: t("potential.node"),
      cell: (n) => (
        <span className="flex items-center gap-2" style={{ paddingRight: (n.path_ids.length - 1) * 16 }}>
          <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300 shrink-0">
            {levelLabelByKey.get(n.level) ?? n.level}
          </span>
          <span>{n.name}</span>
        </span>
      ),
      sortValue: (n) => n.name,
      filterValue: (n) => n.name,
    },
    {
      id: "eligible",
      header: t("potential.eligible"),
      headerTooltip: t("potential.eligible_tooltip"),
      cell: (n) => results[n.id]?.raw_eligible_count ?? "-",
      sortValue: (n) => results[n.id]?.raw_eligible_count ?? -1,
    },
    {
      id: "modifiers",
      header: t("potential.modifiers"),
      headerTooltip: t("potential.modifiers_tooltip"),
      cell: (n) => (results[n.id] ? modifierSum(results[n.id]) : "-"),
      sortValue: (n) => (results[n.id] ? modifierSum(results[n.id]) : -Infinity),
    },
    {
      id: "final_potential",
      header: t("potential.final_potential"),
      headerTooltip: t("potential.final_potential_tooltip"),
      cell: (n) => results[n.id]?.final_potential ?? "-",
      sortValue: (n) => results[n.id]?.final_potential ?? -1,
    },
    {
      id: "pct_of_parent",
      header: t("potential.pct_of_parent"),
      headerTooltip: t("potential.pct_of_parent_tooltip"),
      cell: (n) => pctOfParentText(n),
      sortValue: (n) => pctOfParentValue(n) ?? -Infinity,
      exportValue: (n) => {
        const pct = pctOfParentValue(n);
        return pct === null ? "" : Math.round(pct);
      },
    },
  ];
```

Note: `filterValue` is intentionally omitted on `name` in this diff's "to" block only because it's unchanged from the "from" block — keep the existing `filterValue: (n) => n.name,` line as-is (it's shown above; don't delete it).

- [ ] **Step 6: Run typecheck**

Run (from `frontend/`): `npm run typecheck`
Expected: no errors

- [ ] **Step 7: Manual verification in the running app**

Using the preview tooling: navigate to `/planning/potential` and confirm:
- each row's name is preceded by a small gray level badge (e.g. "צוות", "חטיבה") and indented further than its parent
- hovering the "?" affordance / column header for כשירים, התאמות, and פוטנציאל סופי shows the explanatory tooltip text (same interaction pattern as `TransparencyPage.tsx`'s tooltipped columns)
- a new "% מהיחידה האם" column shows a percentage for non-root rows and "—" for root nodes, and the value looks correct (child's פוטנציאל סופי ÷ parent's פוטנציאל סופי)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/planning/PotentialPage.tsx frontend/src/i18n/he.json
git commit -m "feat: hierarchy indentation, column tooltips, and pct-of-parent in potential table"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers spec §2 (rank field, backend). Task 2 covers spec §1 (clickable names) and §2's frontend half (rank column). Task 3 covers spec §3 (hierarchy structure), §4 (tooltips), and §5 (%-of-parent). All five spec sections have a task.
- **Placeholder scan:** no TBD/TODO; every step has complete code.
- **Type consistency:** `SoldierPotentialDetail.rank`, `SoldierDetailOut.rank`, and the frontend `SoldierPotentialDetail.rank` all agree as `str | None` / `string | null`. `pctOfParentValue`/`pctOfParentText` names are used consistently between Step 4 and Step 5 of Task 3. `levelLabelByKey` name matches between Task 3 Step 3 and Step 5.
- **Task boundaries:** Task 3 folds the hierarchy-indent, tooltip, and %-of-parent changes into one task instead of three, because all three edit the same `cols` array in the same few lines — splitting them would mean sequential edits to overlapping code for no independent-testability benefit (they're one visual review anyway).
