# Transparency table: פטורים column + subunit exemption aggregates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scope-gated פטורים column to the transparency soldiers tab, and role-gated exemption-count aggregates (גלובלי/חלקי/זמני) to the sub-units tab, so both the on-screen table and its Excel export work as a "potential table."

**Architecture:** `transparency_rows()` in `backend/app/services/scoring.py` gains a `viewer` param, computes each soldier's active exemptions, and returns `{rows, can_see_exemption_aggregates}` instead of a bare list. Per-soldier exemption text is redacted to `"חסוי"` unless the viewer has responsibility scope over that soldier's node (reusing `scope_root_ids`/`path_ids`, no admin bypass). The three boolean aggregate flags are included on every row only when the viewer is an admin or holds any scope at all (coarse gate) — otherwise omitted entirely. The frontend renders the soldiers-tab column directly from the redacted string, and rolls the booleans up per subtree for the sub-units tab, falling back to `חסוי` when the coarse gate fails.

**Tech Stack:** FastAPI + SQLAlchemy + pytest (backend), React + TypeScript + Vitest (frontend).

---

## Reference: spec

Full design at `docs/superpowers/specs/2026-07-02-transparency-exemptions-column-design.md`.

---

### Task 1: Backend — exemption classification & scope-gated fields in `transparency_rows()`

**Files:**
- Modify: `backend/app/services/scoring.py:12-23` (imports), `418-495` (`transparency_rows`)
- Modify: `backend/app/routes/score_adjustments.py:83` (caller)
- Test: `backend/tests/unit/test_scoring_service.py`

- [ ] **Step 1: Write failing tests for the new exemption fields**

Add to `backend/tests/unit/test_scoring_service.py` (after the existing `test_normalised_and_transparency`, i.e. after line 237):

```python
def test_transparency_exemption_in_scope_shows_real_label(admin_session):
    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-exempt-scope")
    dm = create_soldier(
        admin_session, personal_number="8500010", role="duty_manager", hierarchy_node_id=node.id
    )
    s = create_soldier(admin_session, personal_number="8500011", hierarchy_node_id=node.id)
    et = ExemptionType(name="מגבלה רפואית", is_global=False)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(
            soldier_id=s.id,
            exemption_type_id=et.id,
            start_date=date.today() - timedelta(days=1),
            end_date=date.today() + timedelta(days=30),
        )
    )
    admin_session.commit()

    result = transparency_rows(admin_session, viewer=dm)
    row = next(r for r in result["rows"] if r["soldier_id"] == s.id)
    assert row["exemptions_visible"] is True
    assert row["exemptions_display"].startswith("מגבלה רפואית (חלקי, עד ")
    assert row["has_global_exemption"] is False
    assert row["has_partial_exemption"] is True
    assert row["has_temporary_exemption"] is True


def test_transparency_exemption_out_of_scope_is_redacted(admin_session):
    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-exempt-outscope")
    other_node = create_node(admin_session, level="division", name="div-exempt-other")
    viewer_dm = create_soldier(
        admin_session, personal_number="8500012", role="duty_manager", hierarchy_node_id=other_node.id
    )
    s = create_soldier(admin_session, personal_number="8500013", hierarchy_node_id=node.id)
    et = ExemptionType(name="שחרור", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(soldier_id=s.id, exemption_type_id=et.id, start_date=date.today())
    )
    admin_session.commit()

    result = transparency_rows(admin_session, viewer=viewer_dm)
    row = next(r for r in result["rows"] if r["soldier_id"] == s.id)
    assert row["exemptions_visible"] is False
    assert row["exemptions_display"] == "חסוי"
    # aggregate gate passes (viewer holds a scope somewhere), so booleans are still present
    assert row["has_global_exemption"] is True


def test_transparency_aggregate_flags_absent_for_plain_soldier_viewer(admin_session):
    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-exempt-plain")
    plain_viewer = create_soldier(admin_session, personal_number="8500014", role="soldier")
    s = create_soldier(admin_session, personal_number="8500015", hierarchy_node_id=node.id)
    et = ExemptionType(name="שחרור", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(soldier_id=s.id, exemption_type_id=et.id, start_date=date.today())
    )
    admin_session.commit()

    result = transparency_rows(admin_session, viewer=plain_viewer)
    assert result["can_see_exemption_aggregates"] is False
    row = next(r for r in result["rows"] if r["soldier_id"] == s.id)
    assert row["exemptions_display"] == "חסוי"
    assert row["has_global_exemption"] is None
    assert row["has_partial_exemption"] is None
    assert row["has_temporary_exemption"] is None
```

Also update the existing test that calls `transparency_rows` directly — replace lines 214-237
(`test_normalised_and_transparency`) so it matches the new return shape:

```python
def test_normalised_and_transparency(admin_session):
    s = create_soldier(admin_session, personal_number="8500004")
    s.enrolled_at = date.today() - timedelta(days=10)
    admin_session.flush()
    dt = _dt(admin_session, "שמירה-tr", "2.00")
    loc = _loc(admin_session, "מוצב-tr")
    create_assignment(
        admin_session,
        soldier_id=s.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=3),
        end_date=date.today() - timedelta(days=1),
        notes=None,
        actor_id=None,
    )
    admin_session.flush()
    assert normalised_score(admin_session, soldier=s) == Decimal("4.00") / Decimal("10")
    rows = transparency_rows(admin_session, viewer=s)["rows"]
    mine = next(r for r in rows if r["soldier_id"] == s.id)
    assert mine["cumulative_score"] == Decimal("4.00")
    assert mine["active_days"] == 10
    norms = [r["normalised_score"] for r in rows]
    assert norms == sorted(norms, reverse=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_scoring_service.py -k transparency -v`
Expected: FAIL — `transparency_rows() got an unexpected keyword argument 'viewer'` (or `TypeError`).

- [ ] **Step 3: Implement the exemption classification + scope gating in `scoring.py`**

Add `ExemptionType, SoldierExemption` are already imported (line 12-23) — no import change needed
there. Add one new import at the top of `backend/app/services/scoring.py`, right after the existing
`from app.services.eligibility import inferred_service_type` (line 25):

```python
from app.auth.authz import scope_root_ids
```

Add two helper functions directly above `transparency_rows` (i.e. right before line 418):

```python
def _active_exemptions_by_soldier(
    session: Session,
) -> dict[uuid.UUID, list[tuple[SoldierExemption, ExemptionType]]]:
    today = date.today()
    rows = session.execute(
        select(SoldierExemption, ExemptionType)
        .join(ExemptionType, SoldierExemption.exemption_type_id == ExemptionType.id)
        .where(
            SoldierExemption.start_date <= today,
            or_(
                SoldierExemption.end_date.is_(None),
                SoldierExemption.end_date >= today,
            ),
        )
    ).all()
    by_soldier: dict[uuid.UUID, list[tuple[SoldierExemption, ExemptionType]]] = defaultdict(list)
    for exemption, ex_type in rows:
        by_soldier[exemption.soldier_id].append((exemption, ex_type))
    return by_soldier


def _exemption_label(exemption: SoldierExemption, ex_type: ExemptionType) -> str:
    category = "גלובלי" if ex_type.is_global else "חלקי"
    if exemption.end_date is not None:
        return f"{ex_type.name} ({category}, עד {exemption.end_date.strftime('%d/%m/%Y')})"
    return f"{ex_type.name} ({category})"
```

Change the `transparency_rows` signature (line 418) from:

```python
def transparency_rows(session: Session) -> list[dict[str, Any]]:
```

to:

```python
def transparency_rows(
    session: Session, *, viewer: Soldier | None = None
) -> dict[str, Any]:
```

Right after `exempted_ids = globally_exempted_soldier_ids(session)` (line 427), add:

```python
    exemptions_by_soldier = _active_exemptions_by_soldier(session)
    roots = scope_root_ids(session, viewer) if viewer is not None else set()
    can_see_exemption_aggregates = viewer is not None and (
        viewer.role == "admin" or bool(roots)
    )
```

Inside the `for s in soldiers:` loop, right after `node = nodes.get(s.hierarchy_node_id) if s.hierarchy_node_id else None` (line 461), add:

```python
        soldier_exemptions = exemptions_by_soldier.get(s.id, [])
        in_scope = node is not None and any(root in node.path_ids for root in roots)
        if in_scope:
            exemptions_display = ", ".join(
                _exemption_label(exemption, ex_type) for exemption, ex_type in soldier_exemptions
            )
        else:
            exemptions_display = "חסוי"
        has_global = any(ex_type.is_global for _, ex_type in soldier_exemptions)
        has_partial = any(not ex_type.is_global for _, ex_type in soldier_exemptions)
        has_temporary = any(exemption.end_date is not None for exemption, _ in soldier_exemptions)
```

Inside the row dict literal (lines 466-485), add these keys right after `"is_globally_exempted": s.id in exempted_ids,`:

```python
                "exemptions_display": exemptions_display,
                "exemptions_visible": in_scope,
                "has_global_exemption": has_global if can_see_exemption_aggregates else None,
                "has_partial_exemption": has_partial if can_see_exemption_aggregates else None,
                "has_temporary_exemption": has_temporary if can_see_exemption_aggregates else None,
```

Finally, change the return statement (line 495) from:

```python
    rows.sort(key=lambda r: r["effort_score"], reverse=True)
    return rows
```

to:

```python
    rows.sort(key=lambda r: r["effort_score"], reverse=True)
    return {"rows": rows, "can_see_exemption_aggregates": can_see_exemption_aggregates}
```

- [ ] **Step 4: Update the two other in-repo callers**

`backend/app/services/scoring.py:622` (inside `fairness_components`) — change:

```python
    rows = transparency_rows(session)
```

to:

```python
    rows = transparency_rows(session)["rows"]
```

`backend/app/routes/score_adjustments.py:83` — change:

```python
    rows = transparency_rows(session)
```

to:

```python
    rows = transparency_rows(session, viewer=user)["rows"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_scoring_service.py -k transparency -v`
Expected: PASS (4 tests: the 3 new ones + the updated `test_normalised_and_transparency`).

- [ ] **Step 6: Run the full unit suite for regressions**

Run: `cd backend && pytest tests/unit -q`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/scoring.py backend/app/routes/score_adjustments.py backend/tests/unit/test_scoring_service.py
git commit -m "feat: scope-gate exemption data in transparency_rows"
```

---

### Task 2: Backend — `/scoring/transparency` route returns `{rows, can_see_exemption_aggregates}`

**Files:**
- Modify: `backend/app/routes/scoring.py:21-38` (`TransparencyRow`), `84-89` (`transparency` route)
- Test: `backend/tests/integration/test_scoring_api.py`

- [ ] **Step 1: Write failing/updated route tests**

In `backend/tests/integration/test_scoring_api.py`, replace `test_transparency_open_to_any_authed_user`
(lines 10-14) and `test_transparency_reflects_assignment` (lines 17-37) to match the new response
shape, and add one new test for the redaction behavior:

```python
def test_transparency_open_to_any_authed_user(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5600001", role="soldier")
    r = client.get("/api/scoring/transparency", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["rows"], list)
    assert "can_see_exemption_aggregates" in body


def test_transparency_reflects_assignment(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5600002", role="admin")
    s = create_soldier(admin_session, personal_number="5600003", role="soldier")
    dt = DutyType(name="שמירה-sca", score_per_day=Decimal("2.00"))
    loc = DutyLocation(name="מוצב-sca")
    admin_session.add_all([dt, loc])
    admin_session.commit()
    client.post(
        "/api/assignments",
        headers=auth_headers(admin),
        json={
            "soldier_id": str(s.id),
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-10-01",
            "end_date": "2026-10-03",
        },
    )
    r = client.get("/api/scoring/transparency", headers=auth_headers(admin))
    row = next(x for x in r.json()["rows"] if x["soldier_id"] == str(s.id))
    assert Decimal(row["cumulative_score"]) == Decimal("4.00")


def test_transparency_exemptions_redacted_for_plain_soldier(client: TestClient, admin_session: Session):
    from datetime import date

    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-api-redact")
    viewer = create_soldier(admin_session, personal_number="5600007", role="soldier")
    target = create_soldier(admin_session, personal_number="5600008", hierarchy_node_id=node.id)
    et = ExemptionType(name="שחרור", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(soldier_id=target.id, exemption_type_id=et.id, start_date=date.today())
    )
    admin_session.commit()

    r = client.get("/api/scoring/transparency", headers=auth_headers(viewer))
    body = r.json()
    assert body["can_see_exemption_aggregates"] is False
    row = next(x for x in body["rows"] if x["soldier_id"] == str(target.id))
    assert row["exemptions_display"] == "חסוי"
    assert row["has_global_exemption"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_scoring_api.py -v`
Expected: FAIL — `KeyError: 'rows'` (route still returns a bare list).

- [ ] **Step 3: Update the route**

In `backend/app/routes/scoring.py`, extend the `TransparencyRow` model (lines 21-38) — add these
fields right after `is_globally_exempted: bool = False`:

```python
    exemptions_display: str = ""
    exemptions_visible: bool = False
    has_global_exemption: bool | None = None
    has_partial_exemption: bool | None = None
    has_temporary_exemption: bool | None = None
```

Add a new model right after the `TransparencyRow` class:

```python
class TransparencyOut(BaseModel):
    rows: list[TransparencyRow]
    can_see_exemption_aggregates: bool
```

Change the route (lines 84-89) from:

```python
@router.get("/transparency", response_model=list[TransparencyRow])
def transparency(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[TransparencyRow]:
    return [TransparencyRow(**row) for row in svc.transparency_rows(session)]
```

to:

```python
@router.get("/transparency", response_model=TransparencyOut)
def transparency(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransparencyOut:
    result = svc.transparency_rows(session, viewer=user)
    return TransparencyOut(
        rows=[TransparencyRow(**row) for row in result["rows"]],
        can_see_exemption_aggregates=result["can_see_exemption_aggregates"],
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_scoring_api.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full backend fast suite**

Run: `cd backend && pytest -q`
Expected: PASS, no regressions elsewhere (note: `tests/test_effort_score.py::test_transparency_rows_has_effort_score_key` only inspects source text via `inspect.getsource`, unaffected by this change).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/scoring.py backend/tests/integration/test_scoring_api.py
git commit -m "feat: return can_see_exemption_aggregates + exemption fields from /scoring/transparency"
```

---

### Task 3: Frontend — API types for the new response shape

**Files:**
- Modify: `frontend/src/api/scoring.ts:3-21` (`TransparencyRow`), `48-50` (`getTransparency`)

- [ ] **Step 1: Update `TransparencyRow` and add `TransparencyOut`**

In `frontend/src/api/scoring.ts`, add these fields to the `TransparencyRow` interface (after
`is_globally_exempted: boolean;` on line 17):

```typescript
  exemptions_display: string;
  exemptions_visible: boolean;
  has_global_exemption: boolean | null;
  has_partial_exemption: boolean | null;
  has_temporary_exemption: boolean | null;
```

Add a new interface right after `TransparencyRow`:

```typescript
export interface TransparencyOut {
  rows: TransparencyRow[];
  can_see_exemption_aggregates: boolean;
}
```

- [ ] **Step 2: Update `getTransparency`**

Change (lines 48-50):

```typescript
export async function getTransparency(): Promise<TransparencyRow[]> {
  return (await api.get<TransparencyRow[]>(`/scoring/transparency`)).data;
}
```

to:

```typescript
export async function getTransparency(): Promise<TransparencyOut> {
  return (await api.get<TransparencyOut>(`/scoring/transparency`)).data;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: FAIL at this point — `TransparencyPage.tsx` still calls `.then(setRows)` with the old
bare-array shape. This is expected; Task 4 fixes it.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/scoring.ts
git commit -m "feat: add TransparencyOut type for scope-gated transparency response"
```

---

### Task 4: Frontend — soldiers tab פטורים column

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx:284-311` (state + fetch), `498-684` (`soldierCols`)
- Modify: `frontend/src/i18n/he.json:283-310` (transparency block)

- [ ] **Step 1: Add the i18n key**

In `frontend/src/i18n/he.json`, add this line inside the `"transparency"` block (after
`"exempted_count_tooltip": "{{count}} חיילים פטורים (פטור גלובלי)",` at line 303):

```json
    "exemptions": "פטורים",
```

- [ ] **Step 2: Fix the data fetch to match the new response shape**

In `frontend/src/pages/TransparencyPage.tsx`, add a new state variable after
`const [exportSubRows, setExportSubRows] = useState<SubRow[]>([]);` (line 307):

```typescript
  const [canSeeExemptionAggregates, setCanSeeExemptionAggregates] = useState(false);
```

Change (line 309):

```typescript
  useEffect(() => { void getTransparency().then(setRows); }, []);
```

to:

```typescript
  useEffect(() => {
    void getTransparency().then((out) => {
      setRows(out.rows);
      setCanSeeExemptionAggregates(out.can_see_exemption_aggregates);
    });
  }, []);
```

- [ ] **Step 3: Add the soldiers-tab column**

In `frontend/src/pages/TransparencyPage.tsx`, add a new entry to `soldierCols` (the array starting
at line 498), right after the `unit` column (lines 509-513):

```typescript
    {
      id: "exemptions", header: t("transparency.exemptions"),
      cell: (r) => r.exemptions_display || "—",
      sortValue: (r) => r.exemptions_display,
      filterValue: (r) => r.exemptions_display,
      exportValue: (r) => r.exemptions_display || "—",
    },
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Manually verify column renders**

Run: `cd frontend && npm run lint`
Expected: PASS (zero warnings).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx frontend/src/i18n/he.json
git commit -m "feat: add פטורים column to transparency soldiers tab"
```

---

### Task 5: Frontend — sub-units tab exemption aggregate columns

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx:135-149` (`SubRow`), `400-447` (`subRows`), `687-782` (`subCols`)
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add i18n keys**

In `frontend/src/i18n/he.json`, add these lines inside the `"transparency"` block, right after the
`"exemptions"` key added in Task 4:

```json
    "count_global_exemption": "פטורים גלובליים",
    "count_partial_exemption": "פטורים חלקיים",
    "count_temporary_exemption": "פטורים זמניים",
```

- [ ] **Step 2: Extend the `SubRow` interface**

In `frontend/src/pages/TransparencyPage.tsx`, add these fields to `SubRow` (after `cv_effort: number | null;` on line 148):

```typescript
  count_global_exemption: number | null;
  count_partial_exemption: number | null;
  count_temporary_exemption: number | null;
```

- [ ] **Step 3: Compute the aggregate counts in the `subRows` rollup**

In the `subRows` useMemo (lines 400-447), inside the `traverse` function's `if (nodeRows.length > 0)`
block, add these three fields to the pushed object, right after `cv_effort: (...)` (line 439, before
the closing `});` at line 440):

```typescript
            count_global_exemption: canSeeExemptionAggregates
              ? nodeRows.filter((r) => r.has_global_exemption === true).length
              : null,
            count_partial_exemption: canSeeExemptionAggregates
              ? nodeRows.filter((r) => r.has_partial_exemption === true).length
              : null,
            count_temporary_exemption: canSeeExemptionAggregates
              ? nodeRows.filter((r) => r.has_temporary_exemption === true).length
              : null,
```

Add `canSeeExemptionAggregates` to the `subRows` useMemo dependency array (line 447):

```typescript
  }, [flatNodes, nodePathsMap, rows, canSeeExemptionAggregates]);
```

- [ ] **Step 4: Add the three columns to `subCols`**

In `frontend/src/pages/TransparencyPage.tsx`, add these entries to `subCols` (the array starting at
line 687), right after the `exempted_count` column (lines 704-716):

```typescript
    {
      id: "count_global_exemption", header: t("transparency.count_global_exemption"),
      cell: (r) => r.count_global_exemption === null ? "חסוי" : r.count_global_exemption,
      sortValue: (r) => r.count_global_exemption ?? -1,
      exportValue: (r) => r.count_global_exemption === null ? "חסוי" : r.count_global_exemption,
    },
    {
      id: "count_partial_exemption", header: t("transparency.count_partial_exemption"),
      cell: (r) => r.count_partial_exemption === null ? "חסוי" : r.count_partial_exemption,
      sortValue: (r) => r.count_partial_exemption ?? -1,
      exportValue: (r) => r.count_partial_exemption === null ? "חסוי" : r.count_partial_exemption,
    },
    {
      id: "count_temporary_exemption", header: t("transparency.count_temporary_exemption"),
      cell: (r) => r.count_temporary_exemption === null ? "חסוי" : r.count_temporary_exemption,
      sortValue: (r) => r.count_temporary_exemption ?? -1,
      exportValue: (r) => r.count_temporary_exemption === null ? "חסוי" : r.count_temporary_exemption,
    },
```

- [ ] **Step 5: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx frontend/src/i18n/he.json
git commit -m "feat: add exemption count aggregates to transparency sub-units tab"
```

---

### Task 6: Frontend — page test for the new columns

**Files:**
- Create: `frontend/src/pages/TransparencyPage.test.tsx`

- [ ] **Step 1: Write the test file**

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import TransparencyPage from "./TransparencyPage";
import * as scoringApi from "../api/scoring";
import * as hierarchyApi from "../api/hierarchy";
import type { TransparencyOut, TransparencyRow } from "../api/scoring";

vi.mock("../api/scoring");
vi.mock("../api/hierarchy");

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "viewer-1", role: "admin" } }),
}));

function makeRow(overrides: Partial<TransparencyRow> = {}): TransparencyRow {
  return {
    soldier_id: "s1",
    full_name: "חייל בדיקה",
    node_id: "node-1",
    node_name: "יחידה 1",
    enrolled_at: "2026-01-01",
    active_days: 10,
    shift_count: 2,
    rank: null,
    is_officer: false,
    service_type: "חובה",
    cumulative_score: "1.00",
    score_per_day: "0.10",
    normalised_score: "1.00",
    is_globally_exempted: false,
    effort_score: 0.1,
    c_over_d: 0,
    effort_offset_raw: 0,
    exemptions_display: "",
    exemptions_visible: true,
    has_global_exemption: false,
    has_partial_exemption: false,
    has_temporary_exemption: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(scoringApi.getFairnessComponents).mockRejectedValue(new Error("not needed"));
});

describe("TransparencyPage exemptions column", () => {
  it("renders the exemptions_display value for a visible row", async () => {
    const out: TransparencyOut = {
      rows: [makeRow({ exemptions_display: "מגבלה רפואית (חלקי, עד 15/08/2026)" })],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    render(<MemoryRouter><TransparencyPage /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText("מגבלה רפואית (חלקי, עד 15/08/2026)")).toBeInTheDocument();
    });
  });

  it("renders חסוי for a redacted row", async () => {
    const out: TransparencyOut = {
      rows: [makeRow({ exemptions_display: "חסוי", exemptions_visible: false })],
      can_see_exemption_aggregates: false,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    render(<MemoryRouter><TransparencyPage /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText("חסוי")).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run the test**

Run: `cd frontend && npx vitest run src/pages/TransparencyPage.test.tsx`
Expected: PASS (2 tests). If `getFairnessComponents` rejection causes an unhandled error in the
console, that's expected/harmless — the page already catches it with `.catch(() => {})` (line 311).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/TransparencyPage.test.tsx
git commit -m "test: cover transparency exemptions column visibility"
```

---

### Task 7: Full verification pass

- [ ] **Step 1: Backend fast suite**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 2: Frontend suite**

Run: `cd frontend && npm test && npm run lint && npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Manual smoke check (dev stack)**

Run: `.\dev.ps1` from the repo root, open http://localhost:5173, navigate to the transparency page,
confirm:
- Soldiers tab shows a פטורים column.
- Sub-units tab shows the three new count columns (or חסוי, depending on the logged-in user's role/scope).
- Excel export from both tabs includes the new columns with matching values.
