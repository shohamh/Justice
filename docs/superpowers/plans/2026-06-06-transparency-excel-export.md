# Transparency Page Excel Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two "Export to Excel" buttons on the Transparency page — one per tab — each streaming a `.xlsx` file from a dedicated backend endpoint.

**Architecture:** Two new FastAPI endpoints in `scoring.py` reuse `svc.transparency_rows()` to get data, build an `openpyxl` workbook in memory, and return a `StreamingResponse`. The soldiers endpoint filters by subtree when `node_id` is given. The sub-units endpoint aggregates over all hierarchy nodes. The frontend adds two functions to `scoring.ts` that set `window.location.href` to trigger native browser downloads, and adds one button per tab to `TransparencyPage.tsx`.

**Tech Stack:** Python / FastAPI / openpyxl / `io.BytesIO`, React / TypeScript / `window.location.href`

---

### Task 1: Add openpyxl to dependencies

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add openpyxl to pyproject.toml**

In `backend/pyproject.toml`, add `"openpyxl>=3.1"` to the `dependencies` list (after `python-telegram-bot`):

```toml
  "python-telegram-bot>=21.0",
  "openpyxl>=3.1",
```

- [ ] **Step 2: Install the dependency**

```bash
cd backend && uv sync
```

Expected: lockfile updated, `openpyxl` installed with no errors.

- [ ] **Step 3: Verify importable**

```bash
cd backend && uv run python -c "import openpyxl; print(openpyxl.__version__)"
```

Expected: prints a version like `3.1.x`.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore: add openpyxl>=3.1 dependency for Excel export"
```

---

### Task 2: Backend — soldiers export endpoint

**Files:**
- Modify: `backend/app/routes/scoring.py`
- Create: `backend/tests/integration/test_transparency_export.py`

#### Writing the tests first

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_transparency_export.py`:

```python
import io
import uuid

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_soldiers_export_returns_xlsx(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5700001", role="soldier")
    r = client.get("/api/scoring/transparency/export", headers=auth_headers(s))
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert "חיילים" in wb.sheetnames


def test_soldiers_export_contains_header_row(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5700002", role="soldier")
    r = client.get("/api/scoring/transparency/export", headers=auth_headers(s))
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["חיילים"]
    headers = [ws.cell(1, col).value for col in range(1, 10)]
    assert headers == [
        "שם", "יחידה", "תאריך הצטרפות", "ימים פעילים", "דרגה",
        "כמות משמרות", "ניקוד מצטבר", "ניקוד ליום", "ניקוד מנורמל",
    ]


def test_soldiers_export_node_filter(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5700003", role="admin")
    root = create_node(admin_session, level="division", name="root-exp")
    child = create_node(admin_session, level="unit", name="child-exp", parent=root)
    s_in = create_soldier(
        admin_session, personal_number="5700004", role="soldier",
        hierarchy_node_id=child.id,
    )
    s_out = create_soldier(
        admin_session, personal_number="5700005", role="soldier",
        hierarchy_node_id=root.id,
    )
    # filter by child node — only s_in should appear (root is not in child's subtree)
    r = client.get(
        f"/api/scoring/transparency/export?node_id={child.id}",
        headers=auth_headers(admin),
    )
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["חיילים"]
    names = [ws.cell(row, 1).value for row in range(2, ws.max_row + 1)]
    assert s_in.full_name in names
    assert s_out.full_name not in names


def test_soldiers_export_unknown_node_returns_404(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5700006", role="soldier")
    r = client.get(
        f"/api/scoring/transparency/export?node_id={uuid.uuid4()}",
        headers=auth_headers(s),
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "not_found"


def test_soldiers_export_requires_auth(client: TestClient):
    r = client.get("/api/scoring/transparency/export")
    assert r.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && uv run pytest tests/integration/test_transparency_export.py -v
```

Expected: all 5 fail — route doesn't exist yet (404 from FastAPI, not the app).

#### Implementing the endpoint

- [ ] **Step 3: Add imports and the soldiers export endpoint to scoring.py**

In `backend/app/routes/scoring.py`, add `io` and the new FastAPI/openpyxl imports. Replace the current import block at the top:

```python
from __future__ import annotations

import io
import uuid
from datetime import date, datetime
from decimal import Decimal

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import scoring as svc
```

Then add the following endpoint **after** the existing `transparency` route and **before** the `breakdown` route:

```python
@router.get("/transparency/export")
def transparency_export(
    node_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> StreamingResponse:
    rows = svc.transparency_rows(session)

    if node_id is not None:
        all_nodes = session.execute(select(HierarchyNode)).scalars().all()
        node_ids_in_db = {n.id for n in all_nodes}
        if node_id not in node_ids_in_db:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        subtree_node_ids = {n.id for n in all_nodes if node_id in n.path_ids}
        rows = [r for r in rows if r["node_id"] in subtree_node_ids]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "חיילים"
    ws.append([
        "שם", "יחידה", "תאריך הצטרפות", "ימים פעילים", "דרגה",
        "כמות משמרות", "ניקוד מצטבר", "ניקוד ליום", "ניקוד מנורמל",
    ])
    for r in rows:
        ws.append([
            r["full_name"],
            r["node_name"],
            str(r["enrolled_at"]),
            r["active_days"],
            r["rank"],
            r["shift_count"],
            float(r["cumulative_score"]),
            float(r["score_per_day"]),
            float(r["normalised_score"]),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="transparency.xlsx"'},
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && uv run pytest tests/integration/test_transparency_export.py -v
```

Expected: all 5 pass.

- [ ] **Step 5: Run the full scoring test suite to ensure no regressions**

```bash
cd backend && uv run pytest tests/integration/test_scoring_api.py tests/integration/test_transparency_export.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/scoring.py backend/tests/integration/test_transparency_export.py
git commit -m "feat: add GET /scoring/transparency/export soldiers Excel endpoint"
```

---

### Task 3: Backend — sub-units export endpoint

**Files:**
- Modify: `backend/app/routes/scoring.py`
- Modify: `backend/tests/integration/test_transparency_export.py`

#### Writing the tests first

- [ ] **Step 1: Append the new tests to the existing test file**

Add to the bottom of `backend/tests/integration/test_transparency_export.py`:

```python
def test_sub_units_export_returns_xlsx(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5700010", role="soldier")
    r = client.get("/api/scoring/transparency/sub-units/export", headers=auth_headers(s))
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert "תתי יחידות" in wb.sheetnames


def test_sub_units_export_contains_header_row(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5700011", role="soldier")
    r = client.get("/api/scoring/transparency/sub-units/export", headers=auth_headers(s))
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["תתי יחידות"]
    headers = [ws.cell(1, col).value for col in range(1, 9)]
    assert headers == [
        "יחידה", "כמות חיילים", "חיילים פעילים (%)",
        "ממוצע ימים פעילים", "ממוצע ניקוד לחייל",
        "ממוצע ניקוד לחייל פעיל", "ניקוד ליום (מסגרת)", "ניקוד מנורמל ממוצע",
    ]


def test_sub_units_export_aggregates_per_node(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5700012", role="admin")
    root = create_node(admin_session, level="division", name="root-su-exp")
    child = create_node(admin_session, level="unit", name="child-su-exp", parent=root)
    create_soldier(admin_session, personal_number="5700013", role="soldier",
                   hierarchy_node_id=child.id)
    create_soldier(admin_session, personal_number="5700014", role="soldier",
                   hierarchy_node_id=child.id)
    r = client.get("/api/scoring/transparency/sub-units/export", headers=auth_headers(admin))
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["תתי יחידות"]
    node_names = [ws.cell(row, 1).value for row in range(2, ws.max_row + 1)]
    # Both root and child appear (child has 2 soldiers; root has them via path)
    assert "child-su-exp" in node_names
    assert "root-su-exp" in node_names
    # child row should show count == 2
    child_row_idx = next(i for i, n in enumerate(node_names, start=2) if n == "child-su-exp")
    assert ws.cell(child_row_idx, 2).value == 2


def test_sub_units_export_requires_auth(client: TestClient):
    r = client.get("/api/scoring/transparency/sub-units/export")
    assert r.status_code == 401
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
cd backend && uv run pytest tests/integration/test_transparency_export.py::test_sub_units_export_returns_xlsx tests/integration/test_transparency_export.py::test_sub_units_export_contains_header_row tests/integration/test_transparency_export.py::test_sub_units_export_aggregates_per_node tests/integration/test_transparency_export.py::test_sub_units_export_requires_auth -v
```

Expected: all 4 fail — route doesn't exist yet.

#### Implementing the endpoint

- [ ] **Step 3: Add the sub-units export endpoint to scoring.py**

Add the following after the `transparency_export` endpoint and before the `breakdown` endpoint in `backend/app/routes/scoring.py`:

```python
@router.get("/transparency/sub-units/export")
def transparency_sub_units_export(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> StreamingResponse:
    rows = svc.transparency_rows(session)
    all_nodes = session.execute(select(HierarchyNode)).scalars().all()

    # Map each node id to its path_ids for quick lookup
    node_path_map: dict[uuid.UUID, list[uuid.UUID]] = {n.id: n.path_ids for n in all_nodes}

    # Sort nodes: shallowest first, then alphabetically
    sorted_nodes = sorted(all_nodes, key=lambda n: (len(n.path_ids), n.name))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "תתי יחידות"
    ws.append([
        "יחידה", "כמות חיילים", "חיילים פעילים (%)",
        "ממוצע ימים פעילים", "ממוצע ניקוד לחייל",
        "ממוצע ניקוד לחייל פעיל", "ניקוד ליום (מסגרת)", "ניקוד מנורמל ממוצע",
    ])

    for node in sorted_nodes:
        node_rows = [
            r for r in rows
            if r["node_id"] is not None and node.id in node_path_map.get(r["node_id"], [])
        ]
        if not node_rows:
            continue

        count = len(node_rows)
        active_rows = [r for r in node_rows if r["cumulative_score"] > Decimal("0")]
        active_count = len(active_rows)
        active_pct = round(active_count / count * 100)
        avg_cumulative = float(sum(r["cumulative_score"] for r in node_rows) / count)
        avg_cumulative_active = (
            float(sum(r["cumulative_score"] for r in active_rows) / len(active_rows))
            if active_rows else 0.0
        )
        total_score_per_day = float(sum(r["score_per_day"] for r in node_rows))
        avg_active_days = round(sum(r["active_days"] for r in node_rows) / count)
        avg_normalised = float(sum(r["normalised_score"] for r in node_rows) / count)

        ws.append([
            node.name,
            count,
            active_pct,
            avg_active_days,
            avg_cumulative,
            avg_cumulative_active,
            total_score_per_day,
            avg_normalised,
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="sub-units.xlsx"'},
    )
```

- [ ] **Step 4: Run all export tests to verify they pass**

```bash
cd backend && uv run pytest tests/integration/test_transparency_export.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 5: Run the full scoring test suite**

```bash
cd backend && uv run pytest tests/integration/test_scoring_api.py tests/integration/test_transparency_export.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/scoring.py backend/tests/integration/test_transparency_export.py
git commit -m "feat: add GET /scoring/transparency/sub-units/export Excel endpoint"
```

---

### Task 4: Frontend — add download functions to scoring.ts

**Files:**
- Modify: `frontend/src/api/scoring.ts`

- [ ] **Step 1: Add the two download functions**

In `frontend/src/api/scoring.ts`, append the following two functions before the trailing newline at the end of the file:

```typescript
export function downloadTransparencyExport(nodeId: string | null): void {
  const params = nodeId ? `?node_id=${nodeId}` : "";
  window.location.href = `/api/scoring/transparency/export${params}`;
}

export function downloadSubUnitsExport(): void {
  window.location.href = `/api/scoring/transparency/sub-units/export`;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/scoring.ts
git commit -m "feat: add downloadTransparencyExport and downloadSubUnitsExport to scoring API"
```

---

### Task 5: Frontend — add export buttons to TransparencyPage.tsx

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx`

- [ ] **Step 1: Update the scoring import to include the new download functions**

In `frontend/src/pages/TransparencyPage.tsx`, replace the existing scoring import line:

```typescript
import { Breakdown, TransparencyRow, getBreakdown, getTransparency } from "../api/scoring";
```

with:

```typescript
import { Breakdown, TransparencyRow, getBreakdown, getTransparency, downloadTransparencyExport, downloadSubUnitsExport } from "../api/scoring";
```

- [ ] **Step 2: Add the export buttons inside the header div**

In `TransparencyPage.tsx`, the header div currently ends like this (around line 311):

```tsx
          </div>
        </div>

        {/* Tabs */}
        <TabBar tabs={["חיילים", "תתי יחידות"]} active={tab} onChange={setTab} />
```

Replace that closing `</div>` / `</div>` with the buttons inserted before the outer closing tag:

```tsx
          </div>

          {tab === 0 && (
            <button
              className="text-sm text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700 px-3 py-1 rounded hover:bg-green-50 dark:hover:bg-green-950"
              onClick={() => downloadTransparencyExport(selectedNodeId)}
            >
              📥 ייצוא לאקסל
            </button>
          )}
          {tab === 1 && (
            <button
              className="text-sm text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700 px-3 py-1 rounded hover:bg-green-50 dark:hover:bg-green-950"
              onClick={() => downloadSubUnitsExport()}
            >
              📥 ייצוא לאקסל
            </button>
          )}
        </div>

        {/* Tabs */}
        <TabBar tabs={["חיילים", "תתי יחידות"]} active={tab} onChange={setTab} />
```

The first `</div>` closes the `<div className="relative" ...>` tree-filter wrapper; the second `</div>` closes the outer `<div className="flex items-center justify-between gap-4" dir="rtl">` header div.

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Smoke-test in the browser**

```bash
cd frontend && pnpm dev
```

Open http://localhost:5173, log in, navigate to the Transparency page and verify:
- Tab 0 (חיילים): green "📥 ייצוא לאקסל" button is visible in the header row alongside the tree filter.
- Tab 1 (תתי יחידות): switching tabs shows the same green button (tree filter hidden, export button visible).
- Clicking either button triggers a file download (.xlsx).
- On tab 0 with an active unit filter, the downloaded file contains only soldiers from that subtree.

Press Ctrl+C when done.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx
git commit -m "feat: add Excel export buttons to Transparency page"
```
