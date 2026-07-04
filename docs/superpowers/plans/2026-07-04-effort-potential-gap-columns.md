# Effort-vs-Potential Gap Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shared backend calculation of per-hierarchy-node total effort vs. potential (sibling-relative and organization-global), and surface it as sortable, color-coded "gap" columns on both the Transparency and Potential pages.

**Architecture:** A new backend service function computes, for every hierarchy node, `final_potential` (existing), a new `total_effort` (sum of per-soldier `effort_score` across the node's subtree), and four derived ratios (sibling share/gap, global share/gap). One new route exposes this as a single list. Both frontend pages fetch it once and merge it into their existing per-node row data by `node_id`.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript (frontend), pytest (backend tests), existing `ColDef`/`DataTable` column pattern (frontend).

Spec: [docs/superpowers/specs/2026-07-04-shift-responsibility-and-effort-gap-design.md](../specs/2026-07-04-shift-responsibility-and-effort-gap-design.md) — "Feature 2" section.

## Global Constraints

- Backend area marker: files under `backend/app/services/tests/` are auto-assigned pytest markers by filename; this feature's tests will be assigned `scoring` (per `pyproject.toml` — "scoring: cumulative score / transparency / effort-score reporting"). No manual `pytestmark` needed.
- Ratios are computed as floats; when a denominator is 0, the corresponding share/gap must be `None` (not 0, not an exception) — division by zero must never propagate to the API.
- Reuse `compute_potential` (`backend/app/services/potential.py:105`) unchanged for `final_potential` — do not reimplement potential logic.
- Reuse the existing reset-date/planning-horizon rules for effort (currently inlined in `transparency_rows`, `backend/app/services/scoring.py:470-496`) — extract, don't duplicate.

---

### Task 1: Extract `effort_scores_by_soldier` helper from `transparency_rows`

**Files:**
- Modify: `backend/app/services/scoring.py:452-497` (extract shared logic; `transparency_rows` becomes a caller)
- Test: `backend/app/services/tests/test_scoring.py` (add a focused test for the new function; find this file first to match existing fixture/import style — it already has tests exercising `transparency_rows`)

**Interfaces:**
- Produces: `effort_scores_by_soldier(session: Session, soldiers: list[Soldier]) -> dict[uuid.UUID, float]` — effort score (0..~1+ scale-invariant ratio, same value as `TransparencyRow.effort_score` today) keyed by soldier id. Soldiers with no computable effort data are omitted from the dict (callers should `.get(id, 0.0)`).

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_scoring.py` (adjust imports/fixture name if the file's existing tests use a different session fixture than `app_session` — check the top of the file first):

```python
def test_effort_scores_by_soldier_matches_transparency_rows(app_session):
    from app.services.scoring import effort_scores_by_soldier, transparency_rows

    node = create_node(app_session, level="team", name="Effort Extraction Co", parent_id=None)
    app_session.flush()
    s1 = _make_soldier(app_session, node_id=node.id)
    s2 = _make_soldier(app_session, node_id=node.id)
    app_session.commit()

    soldiers = [s1, s2]
    direct = effort_scores_by_soldier(app_session, soldiers)
    via_transparency = {
        r["soldier_id"]: r["effort_score"] for r in transparency_rows(app_session)["rows"]
    }
    assert direct.get(s1.id) == via_transparency.get(s1.id)
    assert direct.get(s2.id) == via_transparency.get(s2.id)
```

(If `test_scoring.py` doesn't already define `_make_soldier`/`create_node` helpers, use whatever equivalent helper the file already imports — e.g. `from tests.helpers import create_node, create_soldier` as seen in `test_shift_quotas.py`. Match the file's existing pattern exactly.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_scoring.py::test_effort_scores_by_soldier_matches_transparency_rows -v`
Expected: FAIL with `ImportError: cannot import name 'effort_scores_by_soldier'`

- [ ] **Step 3: Extract the function**

In `backend/app/services/scoring.py`, replace the block currently inside `transparency_rows` (the `# Compute effort scores for all active soldiers` section, roughly lines 470-496) with a call to a new top-level function, and move the extracted logic into it:

```python
def effort_scores_by_soldier(
    session: Session, soldiers: list[Soldier]
) -> dict[uuid.UUID, float]:
    """Effort score (scale-invariant A_i/W_i ratio) per soldier id, using the
    same reset-date/planning-horizon rules as the transparency page."""
    from app.services.effort_score import compute_effort_data, quarter_start
    from app.services.settings_loader import SettingNotFound, get_setting

    today = date.today()
    try:
        reset_raw = get_setting(session, "fairness.reset_date")
        reset_date = date.fromisoformat(str(reset_raw))
    except (SettingNotFound, ValueError, Exception):
        reset_date = quarter_start(date(today.year - 2, today.month, 1))

    from sqlalchemy import func as sql_func
    latest_published_end = session.execute(
        select(sql_func.max(DutyAssignment.end_date)).where(DutyAssignment.status == "published")
    ).scalar()
    if latest_published_end is not None and latest_published_end >= today:
        planning_start = latest_published_end + timedelta(days=1)
    else:
        planning_start = today

    effort_map = compute_effort_data(
        session,
        soldiers=soldiers,
        planning_start=planning_start,
        planning_end=planning_start,
        reset_date=reset_date,
    )
    return {sid: float(data.effort_score) for sid, data in effort_map.items()}
```

Then in `transparency_rows`, replace the extracted block with:

```python
    effort_by_soldier = effort_scores_by_soldier(session, list(soldiers))
```

And update the per-row lookup further down (currently `effort_data = effort_map.get(s.id)` / `effort_score = float(effort_data.effort_score) if effort_data else 0.0`) — since `c_over_d` and `effort_offset_raw` are still needed per-row from the raw `EffortData`, **keep the original `compute_effort_data` call inline in `transparency_rows` for those two fields**, and additionally call `effort_scores_by_soldier` is redundant in that case.

Correction — to avoid computing effort twice in `transparency_rows` (once via the extracted helper, once inline for `c_over_d`/`effort_offset_raw`), do NOT change `transparency_rows` internals at all. Instead, make `effort_scores_by_soldier` wrap the same `compute_effort_data` call, and have `transparency_rows` keep its own inline call exactly as-is (no behavior change there). This keeps Task 1 a pure *addition* (new function) rather than a risky refactor of already-working code, while still giving Task 2 the shared helper it needs. Re-run Step 1's test against this version — it must still pass, since both `transparency_rows` and `effort_scores_by_soldier` call the identical underlying `compute_effort_data` with the identical arguments and therefore produce identical `effort_score` values for the same soldiers.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_scoring.py::test_effort_scores_by_soldier_matches_transparency_rows -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring.py backend/app/services/tests/test_scoring.py
git commit -m "feat: extract effort_scores_by_soldier helper for reuse outside transparency_rows"
```

---

### Task 2: `compute_node_effort_potential` service function

**Files:**
- Create: `backend/app/services/node_effort_potential.py`
- Test: `backend/app/services/tests/test_node_effort_potential.py`

**Interfaces:**
- Consumes: `compute_potential(session, *, node_id, reference_date) -> PotentialResult` (`backend/app/services/potential.py:105`, `.final_potential: int`); `effort_scores_by_soldier(session, soldiers) -> dict[uuid.UUID, float]` (Task 1).
- Produces:
  ```python
  @dataclass
  class NodeEffortPotential:
      node_id: uuid.UUID
      node_name: str
      final_potential: int
      total_effort: float
      sibling_potential_share: float | None = None
      sibling_effort_share: float | None = None
      sibling_gap: float | None = None
      global_potential_share: float | None = None
      global_effort_share: float | None = None
      global_gap: float | None = None

  def compute_node_effort_potential(
      session: Session, *, reference_date: date
  ) -> dict[uuid.UUID, NodeEffortPotential]: ...
  ```
  Keyed by `node_id`. Later tasks (route in Task 3, and Plan B's auto-assign scoring) consume this dict.

- [ ] **Step 1: Write the failing test**

```python
# backend/app/services/tests/test_node_effort_potential.py
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.db.models import DutyType, Soldier
from app.services.hierarchy import create_node
from app.services.node_effort_potential import compute_node_effort_potential


def _make_soldier(session, *, node_id, rank="טוראי", gender="m"):
    s = Soldier(
        personal_number=str(uuid.uuid4())[:8],
        full_name="Test Soldier",
        password_hash="x",
        hierarchy_node_id=node_id,
        rank=rank,
        gender=gender,
    )
    session.add(s)
    session.flush()
    return s


def test_sibling_shares_sum_to_one(app_session):
    parent = create_node(app_session, level="unit", name="Gap Parent", parent_id=None)
    app_session.flush()
    child_a = create_node(app_session, level="team", name="Gap Child A", parent_id=parent.id)
    child_b = create_node(app_session, level="team", name="Gap Child B", parent_id=parent.id)
    app_session.flush()
    for _ in range(3):
        _make_soldier(app_session, node_id=child_a.id)
    for _ in range(1):
        _make_soldier(app_session, node_id=child_b.id)
    app_session.add(DutyType(name="שמירה גאפ", score_per_day=Decimal("1.0"), requirements={}))
    app_session.commit()

    results = compute_node_effort_potential(app_session, reference_date=date(2026, 7, 4))

    a = results[child_a.id]
    b = results[child_b.id]
    assert a.sibling_potential_share is not None and b.sibling_potential_share is not None
    assert abs((a.sibling_potential_share + b.sibling_potential_share) - 1.0) < 1e-9
    # 3 eligible soldiers in A vs 1 in B -> A should hold 3/4 of the sibling potential share
    assert abs(a.sibling_potential_share - 0.75) < 1e-9


def test_gap_is_none_when_potential_share_is_zero(app_session):
    parent = create_node(app_session, level="unit", name="Gap Parent Zero", parent_id=None)
    app_session.flush()
    child = create_node(app_session, level="team", name="Gap Child Zero", parent_id=parent.id)
    app_session.flush()
    app_session.commit()

    results = compute_node_effort_potential(app_session, reference_date=date(2026, 7, 4))

    r = results[child.id]
    # no soldiers anywhere under this parent -> zero total potential among siblings
    assert r.sibling_gap is None


def test_global_share_relative_to_top_level_roots(app_session):
    root_a = create_node(app_session, level="corps", name="Gap Root A", parent_id=None)
    root_b = create_node(app_session, level="corps", name="Gap Root B", parent_id=None)
    app_session.flush()
    for _ in range(2):
        _make_soldier(app_session, node_id=root_a.id)
    for _ in range(2):
        _make_soldier(app_session, node_id=root_b.id)
    app_session.add(DutyType(name="שמירה גלובלי", score_per_day=Decimal("1.0"), requirements={}))
    app_session.commit()

    results = compute_node_effort_potential(app_session, reference_date=date(2026, 7, 4))

    a = results[root_a.id]
    b = results[root_b.id]
    assert a.global_potential_share is not None
    assert abs(a.global_potential_share - 0.5) < 1e-6
    assert abs(b.global_potential_share - 0.5) < 1e-6
```

(These tests assume `app_session` starts with no pre-existing hierarchy nodes/soldiers, matching the convention already used in `test_potential.py` and `test_shift_quotas.py`. If the shared fixture is not perfectly isolated — e.g. other tests' nodes leak into "top-level roots" — scope assertions to `results[root_a.id]` / `results[child_a.id]` specifically rather than asserting on totals across all nodes, as done above.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_node_effort_potential.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.node_effort_potential'`

- [ ] **Step 3: Implement**

```python
# backend/app/services/node_effort_potential.py
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HierarchyNode, Soldier
from app.services.potential import compute_potential
from app.services.scoring import effort_scores_by_soldier


@dataclass
class NodeEffortPotential:
    node_id: uuid.UUID
    node_name: str
    final_potential: int
    total_effort: float
    sibling_potential_share: float | None = None
    sibling_effort_share: float | None = None
    sibling_gap: float | None = None
    global_potential_share: float | None = None
    global_effort_share: float | None = None
    global_gap: float | None = None


def compute_node_effort_potential(
    session: Session, *, reference_date: date
) -> dict[uuid.UUID, NodeEffortPotential]:
    """Per-node final_potential, total_effort (sum of per-soldier effort_score
    across the node's subtree), and share/gap ratios both among direct
    siblings and relative to the whole organization (top-level roots)."""
    nodes = list(session.execute(select(HierarchyNode)).scalars().all())
    soldiers = list(
        session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    )
    effort_by_soldier = effort_scores_by_soldier(session, soldiers)

    # node_id -> set of node ids in its own subtree (nodes whose path_ids contains node_id)
    subtree_node_ids_by_node: dict[uuid.UUID, set[uuid.UUID]] = {
        node.id: {n2.id for n2 in nodes if node.id in n2.path_ids} for node in nodes
    }

    results: dict[uuid.UUID, NodeEffortPotential] = {}
    for node in nodes:
        potential = compute_potential(
            session, node_id=node.id, reference_date=reference_date
        ).final_potential
        subtree_ids = subtree_node_ids_by_node[node.id]
        total_effort = sum(
            effort_by_soldier.get(s.id, 0.0) for s in soldiers if s.hierarchy_node_id in subtree_ids
        )
        results[node.id] = NodeEffortPotential(
            node_id=node.id,
            node_name=node.name,
            final_potential=potential,
            total_effort=total_effort,
        )

    def _apply_shares(group: list[HierarchyNode], potential_attr: str, effort_attr: str, gap_attr: str) -> None:
        total_potential = sum(max(results[n.id].final_potential, 0) for n in group)
        total_effort = sum(results[n.id].total_effort for n in group)
        for n in group:
            r = results[n.id]
            p_share = (max(r.final_potential, 0) / total_potential) if total_potential > 0 else None
            e_share = (r.total_effort / total_effort) if total_effort > 0 else None
            setattr(r, potential_attr, p_share)
            setattr(r, effort_attr, e_share)
            if p_share is not None and p_share > 0 and e_share is not None:
                setattr(r, gap_attr, e_share / p_share)

    by_parent: dict[uuid.UUID | None, list[HierarchyNode]] = defaultdict(list)
    for node in nodes:
        by_parent[node.parent_id].append(node)
    for siblings in by_parent.values():
        _apply_shares(siblings, "sibling_potential_share", "sibling_effort_share", "sibling_gap")

    top_level_roots = [n for n in nodes if n.parent_id is None]
    if top_level_roots:
        _apply_shares(top_level_roots, "global_potential_share", "global_effort_share", "global_gap")
        # Non-root nodes: global share is relative to the org total, not just their own parent group.
        org_total_potential = sum(max(results[n.id].final_potential, 0) for n in top_level_roots)
        org_total_effort = sum(results[n.id].total_effort for n in top_level_roots)
        for node in nodes:
            if node.parent_id is None:
                continue
            r = results[node.id]
            p_share = (max(r.final_potential, 0) / org_total_potential) if org_total_potential > 0 else None
            e_share = (r.total_effort / org_total_effort) if org_total_effort > 0 else None
            r.global_potential_share = p_share
            r.global_effort_share = e_share
            r.global_gap = (e_share / p_share) if (p_share is not None and p_share > 0 and e_share is not None) else None

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_node_effort_potential.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/node_effort_potential.py backend/app/services/tests/test_node_effort_potential.py
git commit -m "feat: add compute_node_effort_potential (sibling/global effort-vs-potential shares)"
```

---

### Task 3: `GET /potential/effort-gap` route

**Files:**
- Modify: `backend/app/routes/potential.py` (add response models + endpoint, near the existing `GET ""` handler at line 83)
- Test: `backend/tests/integration/test_potential_api.py` (find this file first — if it doesn't exist, check `backend/tests/integration/` for the existing potential API test file and match its fixture/client style, e.g. `test_shift_quotas_api.py`'s pattern of an authenticated test client)

**Interfaces:**
- Consumes: `compute_node_effort_potential(session, *, reference_date) -> dict[uuid.UUID, NodeEffortPotential]` (Task 2).
- Produces: `GET /potential/effort-gap?reference_date=YYYY-MM-DD` (optional; defaults to today) → `{"nodes": [{"node_id", "node_name", "final_potential", "total_effort", "sibling_potential_share", "sibling_effort_share", "sibling_gap", "global_potential_share", "global_effort_share", "global_gap"}, ...]}`. Frontend `getEffortGap()` (Task 4) consumes this exact shape.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/integration/test_potential_api.py (or the equivalent existing file)
def test_effort_gap_endpoint_returns_all_nodes(admin_client, admin_session):
    from app.services.hierarchy import create_node

    node = create_node(admin_session, level="unit", name="Effort Gap API Co", parent_id=None)
    admin_session.commit()

    resp = admin_client.get("/potential/effort-gap")
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["node_id"] for n in body["nodes"]}
    assert str(node.id) in node_ids
    entry = next(n for n in body["nodes"] if n["node_id"] == str(node.id))
    assert "sibling_gap" in entry
    assert "global_gap" in entry
```

(Match whatever authenticated-client fixture name the existing integration tests in this directory actually use — e.g. `admin_client`/`admin_session` as seen across `test_shift_quotas_api.py`; adjust if the real fixture names differ.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/integration/test_potential_api.py::test_effort_gap_endpoint_returns_all_nodes -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Implement the route**

In `backend/app/routes/potential.py`, add near the top-level imports:

```python
from app.services.node_effort_potential import compute_node_effort_potential
```

Add after the existing `get_potential` handler (after line 96):

```python
class NodeEffortPotentialOut(BaseModel):
    node_id: uuid.UUID
    node_name: str
    final_potential: int
    total_effort: float
    sibling_potential_share: float | None
    sibling_effort_share: float | None
    sibling_gap: float | None
    global_potential_share: float | None
    global_effort_share: float | None
    global_gap: float | None


class EffortGapOut(BaseModel):
    nodes: list[NodeEffortPotentialOut]


@router.get("/effort-gap", response_model=EffortGapOut)
def get_effort_gap(
    reference_date: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> EffortGapOut:
    authorize(session, user, Action.POTENTIAL_READ, target_node=None)
    ref = date.fromisoformat(reference_date) if reference_date else date.today()
    results = compute_node_effort_potential(session, reference_date=ref)
    return EffortGapOut(
        nodes=[
            NodeEffortPotentialOut(
                node_id=r.node_id,
                node_name=r.node_name,
                final_potential=r.final_potential,
                total_effort=r.total_effort,
                sibling_potential_share=r.sibling_potential_share,
                sibling_effort_share=r.sibling_effort_share,
                sibling_gap=r.sibling_gap,
                global_potential_share=r.global_potential_share,
                global_effort_share=r.global_effort_share,
                global_gap=r.global_gap,
            )
            for r in results.values()
        ]
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/integration/test_potential_api.py::test_effort_gap_endpoint_returns_all_nodes -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/potential.py backend/tests/integration/test_potential_api.py
git commit -m "feat: add GET /potential/effort-gap endpoint"
```

---

### Task 4: Frontend API client for the effort-gap endpoint

**Files:**
- Modify: `frontend/src/api/potential.ts`

**Interfaces:**
- Produces:
  ```ts
  export interface NodeEffortPotential {
    node_id: string;
    node_name: string;
    final_potential: number;
    total_effort: number;
    sibling_potential_share: number | null;
    sibling_effort_share: number | null;
    sibling_gap: number | null;
    global_potential_share: number | null;
    global_effort_share: number | null;
    global_gap: number | null;
  }
  export async function getEffortGap(referenceDate?: string): Promise<NodeEffortPotential[]>;
  ```
  Consumed by Task 5 (Transparency page) and Task 6 (Potential page).

- [ ] **Step 1: Add the types + function**

Append to `frontend/src/api/potential.ts`:

```ts
export interface NodeEffortPotential {
  node_id: string;
  node_name: string;
  final_potential: number;
  total_effort: number;
  sibling_potential_share: number | null;
  sibling_effort_share: number | null;
  sibling_gap: number | null;
  global_potential_share: number | null;
  global_effort_share: number | null;
  global_gap: number | null;
}

export async function getEffortGap(referenceDate?: string): Promise<NodeEffortPotential[]> {
  const r = await api.get<{ nodes: NodeEffortPotential[] }>("/potential/effort-gap", {
    params: { reference_date: referenceDate },
  });
  return r.data.nodes;
}
```

- [ ] **Step 2: Manually verify against the running backend**

Run: `.\dev.ps1` (or ensure it's already running), then in the browser devtools console on any authenticated page:
```js
fetch("/api/potential/effort-gap").then(r => r.json()).then(console.log)
```
Expected: a JSON object with a `nodes` array containing entries with `sibling_gap`/`global_gap` fields (adjust the fetch URL prefix to match this project's actual API base path if different from `/api`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/potential.ts
git commit -m "feat: add getEffortGap API client function"
```

---

### Task 5: Transparency page — sibling/global gap columns

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx`

**Interfaces:**
- Consumes: `getEffortGap()` (Task 4), existing `SubRow` interface (`TransparencyPage.tsx:136-153`), existing `subRows` memo (`TransparencyPage.tsx:410-...`).

- [ ] **Step 1: Fetch the effort-gap data and extend `SubRow`**

Add state near the other `useState` calls in `TransparencyPage` (around line 288-309):

```tsx
const [effortGapByNode, setEffortGapByNode] = useState<Map<string, NodeEffortPotential>>(new Map());
```

Add the import at the top of the file:

```tsx
import { getEffortGap, NodeEffortPotential } from "../api/potential";
```

Add a `useEffect` alongside the other data-fetching effects to load it once on mount:

```tsx
useEffect(() => {
  void getEffortGap().then((rows) => {
    setEffortGapByNode(new Map(rows.map((r) => [r.node_id, r])));
  }).catch(() => {});
}, []);
```

Extend the `SubRow` interface (`TransparencyPage.tsx:136-153`) with the four new fields:

```tsx
interface SubRow {
  // ...existing fields unchanged...
  sibling_gap: number | null;
  global_gap: number | null;
}
```

In `buildSubRow` (`TransparencyPage.tsx:414`), add the two new fields to the returned object, reading from `effortGapByNode` (captured via closure — `buildSubRow` is defined inside the `subRows` `useMemo`, so add `effortGapByNode` to that memo's dependency array):

```tsx
sibling_gap: effortGapByNode.get(nodeId)?.sibling_gap ?? null,
global_gap: effortGapByNode.get(nodeId)?.global_gap ?? null,
```

Update the `subRows` `useMemo` dependency array to include `effortGapByNode`.

- [ ] **Step 2: Add the two new columns**

Near the existing `avg_effort`/`cv_effort` column definitions (`TransparencyPage.tsx:815-837`), add two new `ColDef<SubRow>` entries using the same `gapColor` helper defined once and reused by both:

```tsx
function gapColor(gap: number | null): string {
  if (gap === null) return "text-gray-400";
  if (gap > 1.3) return "text-red-600 dark:text-red-400 font-semibold";
  if (gap < 0.7) return "text-blue-600 dark:text-blue-400 font-semibold";
  return "text-gray-700 dark:text-gray-300";
}

function formatGap(gap: number | null): string {
  return gap === null ? "—" : gap.toFixed(2);
}
```

```tsx
{
  id: "sibling_gap",
  header: t("transparency.subunit_sibling_gap"),
  cell: (r) => <span className={gapColor(r.sibling_gap)}>{formatGap(r.sibling_gap)}</span>,
  sortValue: (r) => r.sibling_gap ?? -1,
  exportValue: (r) => formatGap(r.sibling_gap),
},
{
  id: "global_gap",
  header: t("transparency.subunit_global_gap"),
  cell: (r) => <span className={gapColor(r.global_gap)}>{formatGap(r.global_gap)}</span>,
  sortValue: (r) => r.global_gap ?? -1,
  exportValue: (r) => formatGap(r.global_gap),
},
```

Place these column definitions directly after the existing `cv_effort` column (`TransparencyPage.tsx:822-837`) in the same array.

- [ ] **Step 3: Add i18n keys**

In `frontend/src/i18n/he.json`, under the `transparency` section (find the existing `subunit_avg_effort`/`subunit_cv_effort` keys and add alongside them):

```json
"subunit_sibling_gap": "פער מול אחים (יחס)",
"subunit_global_gap": "פער מול הארגון (יחס)"
```

- [ ] **Step 4: Manually verify in the browser**

Run: start the dev stack, open the Transparency page, switch to the "sub_units" tab, confirm the two new columns render with numeric ratios and color coding, and that clicking the column header sorts by the ratio.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx frontend/src/i18n/he.json
git commit -m "feat: add sibling/global effort-vs-potential gap columns to Transparency page"
```

---

### Task 6: Potential page — sibling/global gap columns

**Files:**
- Modify: `frontend/src/pages/planning/PotentialPage.tsx`

**Interfaces:**
- Consumes: `getEffortGap()` (Task 4), existing `results: Record<string, PotentialResult>` state (`PotentialPage.tsx:40`), existing node-table `ColDef` array (around `PotentialPage.tsx:254`).

- [ ] **Step 1: Fetch the effort-gap data**

Add state and effect near the existing `results` state (`PotentialPage.tsx:40`, `useEffect` block around line 112):

```tsx
const [effortGapByNode, setEffortGapByNode] = useState<Map<string, NodeEffortPotential>>(new Map());

useEffect(() => {
  void getEffortGap(referenceDate).then((rows) => {
    setEffortGapByNode(new Map(rows.map((r) => [r.node_id, r])));
  }).catch(() => {});
}, [referenceDate]);
```

Add the import:

```tsx
import { getEffortGap, NodeEffortPotential } from "../../api/potential";
```

(`referenceDate` already exists as page state per `PotentialPage.tsx:39`; reusing it keeps the gap calculation consistent with whatever date the potential table is showing.)

- [ ] **Step 2: Add the two new columns**

Reuse the same `gapColor`/`formatGap` helpers from Task 5 — since they're small and pure, duplicate them locally in `PotentialPage.tsx` rather than introducing a shared import for two three-line functions (YAGNI: not worth a new shared module for this).

Near the existing `final_potential` column (`PotentialPage.tsx:254-258`), add:

```tsx
{
  id: "sibling_gap",
  header: t("potential.sibling_gap"),
  cell: (n) => <span className={gapColor(effortGapByNode.get(n.id)?.sibling_gap ?? null)}>{formatGap(effortGapByNode.get(n.id)?.sibling_gap ?? null)}</span>,
  sortValue: (n) => effortGapByNode.get(n.id)?.sibling_gap ?? -1,
},
{
  id: "global_gap",
  header: t("potential.global_gap"),
  cell: (n) => <span className={gapColor(effortGapByNode.get(n.id)?.global_gap ?? null)}>{formatGap(effortGapByNode.get(n.id)?.global_gap ?? null)}</span>,
  sortValue: (n) => effortGapByNode.get(n.id)?.global_gap ?? -1,
},
```

(Match the exact `ColDef` generic type parameter used by the surrounding array — inspect `PotentialPage.tsx:254` for whether it's `ColDef<NodeDTO>` or another row type, and use the same `n` accessor pattern already used by neighboring columns for `n.id`.)

- [ ] **Step 3: Add i18n keys**

In `frontend/src/i18n/he.json`, under the `potential` section:

```json
"sibling_gap": "פער מול אחים (יחס)",
"global_gap": "פער מול הארגון (יחס)"
```

- [ ] **Step 4: Manually verify in the browser**

Run: start the dev stack, open the Potential page, confirm the two new columns render with numeric ratios and color coding, and sorting works.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/planning/PotentialPage.tsx frontend/src/i18n/he.json
git commit -m "feat: add sibling/global effort-vs-potential gap columns to Potential page"
```

---

## Self-Review Notes

- **Spec coverage:** Feature 2's endpoint, both share scopes, both pages, ratio format, and color-coded sortable columns are all covered (Tasks 1-6). "No separate ranking column" — satisfied by making both gap columns sortable instead.
- **Type consistency:** `NodeEffortPotential` (frontend) field names match `NodeEffortPotentialOut` (backend) exactly; `sibling_gap`/`global_gap` naming is consistent across service, route, and both frontend pages.
- **Dependency into Plan B:** Plan B's "Auto assign unit responsibility" button uses `total_effort` per node as `past_effort` — it depends on Task 2's `compute_node_effort_potential` (already returns `total_effort` per node), not on any UI task here. Plan B can start once Task 2 is merged, without waiting for Tasks 3-6.
