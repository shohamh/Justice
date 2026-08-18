# Batch 1 — Quick UI Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five small, independent user-reported UI bugs (items 8, 9, 10, 15, 3 from the 2026-08-18 triage spec): transfer requests showing a raw id instead of the soldier's name, a wrong-username login error showing "network error", the announcement unit picker rendering a flat list instead of a tree, several exemption/constraint date ranges rendering visually reversed under RTL, and registration-flow date fields lacking test coverage for typed (not just icon-picked) input.

**Architecture:** Each task is a self-contained frontend (mostly) or backend+frontend fix in its own file(s), independently testable, with no shared code between tasks except existing utilities (`formatDate`, `DateInput`). No new dependencies, no schema changes beyond one new response field.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + Vitest/RTL (frontend), pytest (backend tests).

## Global Constraints

- RBAC: no permission changes in this batch — do not touch `authz.py`.
- `end_date` is exclusive ONLY for assignments/cancellations; exemptions, constraints, dismissals, and call-ups are inclusive. Never call `lastDutyDay()`/`toExclusiveEndDate()` on exemption/constraint/dismissal/call-up dates.
- Zero lint warnings enforced (`npm run lint`, `ruff`). Run `npm run typecheck` / `mypy` before considering a task done.
- Hebrew UI strings for any *new* copy must go in `frontend/src/i18n/he.json` (English keys, Hebrew values) — do not hardcode new Hebrew strings inline if an equivalent i18n key doesn't already exist; check existing keys first since several already cover this batch's needs.
- Source spec: `docs/superpowers/specs/2026-08-18-user-reported-issues-triage-design.md` (Batch 1 section). Do not re-derive product decisions from it — they're restated in full below.

---

## Task 1: Transfer request shows soldier's name (item 8)

**Files:**
- Modify: `backend/app/routes/hierarchy_transfers.py:27-39, 102-107`
- Modify: `frontend/src/api/hierarchyTransfers.ts:3-9`
- Modify: `frontend/src/pages/ApprovalsPage.tsx:799-806`
- Test: `backend/tests/integration/test_hierarchy_transfers_api.py`
- Test: `frontend/src/pages/ApprovalsPage.test.tsx` (create if it doesn't already cover the transfers tab — check first with `Grep -n "transfer" frontend/src/pages/ApprovalsPage.test.tsx`; if it exists, add to it)

**Interfaces:**
- Produces: `TransferOut.soldier_name: str` — every hierarchy-transfers endpoint response now includes this field. `frontend`'s `TransferRequest.soldier_name: string`.

Currently `TransferOut` (backend/app/routes/hierarchy_transfers.py:27-39) has no soldier name, so `ApprovalsPage.tsx:805` falls back to `req.soldier_id.slice(0, 8)` — a truncated UUID — as the display label passed into `SoldierLink`.

- [ ] **Step 1: Write the failing backend test**

Add to `backend/tests/integration/test_hierarchy_transfers_api.py`:

```python
def test_transfer_out_includes_soldier_name(client: TestClient, admin_session: Session):
    src = create_node(admin_session, level="unit", name="name_src")
    dst = create_node(admin_session, level="unit", name="name_dst")
    soldier = create_soldier(admin_session, personal_number="7991020", full_name="נועה כהן", hierarchy_node_id=src.id)
    admin = create_soldier(admin_session, personal_number="7991021", role="admin")
    admin_session.commit()

    resp = client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(soldier.id), "to_node_id": str(dst.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["soldier_name"] == "נועה כהן"

    list_resp = client.get("/api/hierarchy-transfers/pending", headers=auth_headers(admin))
    assert list_resp.status_code == 200
    row = next(r for r in list_resp.json() if r["soldier_id"] == str(soldier.id))
    assert row["soldier_name"] == "נועה כהן"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv\Scripts\python -m pytest tests/integration/test_hierarchy_transfers_api.py::test_transfer_out_includes_soldier_name -v`
Expected: FAIL with a `KeyError`/`AssertionError` — response has no `soldier_name` key (pydantic will actually reject extra dict access, so expect a `KeyError` on `resp.json()["soldier_name"]`).

- [ ] **Step 3: Add `soldier_name` to `TransferOut` and resolve it**

In `backend/app/routes/hierarchy_transfers.py`, change the schema and `_out()`:

```python
class TransferOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str
    from_node_id: uuid.UUID | None
    to_node_id: uuid.UUID
    status: str


def _out(session: Session, req: HierarchyTransferRequest) -> TransferOut:
    soldier = session.get(Soldier, req.soldier_id)
    return TransferOut(
        id=req.id, soldier_id=req.soldier_id,
        soldier_name=soldier.full_name if soldier else str(req.soldier_id),
        from_node_id=req.from_node_id,
        to_node_id=req.to_node_id, status=req.status,
    )
```

Update every call site to pass `session`: `_out(session, req)` at lines 58, 78, 99. For `list_pending` (currently `[_out(r) for r in svc.list_pending_for_approver(...)]`), batch-load names instead of querying per row:

```python
@router.get("/pending", response_model=list[TransferOut])
def list_pending(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[TransferOut]:
    reqs = svc.list_pending_for_approver(session, approver_id=user.id)
    names = {
        s.id: s.full_name
        for s in session.execute(
            select(Soldier).where(Soldier.id.in_({r.soldier_id for r in reqs}))
        ).scalars().all()
    }
    return [
        TransferOut(
            id=r.id, soldier_id=r.soldier_id,
            soldier_name=names.get(r.soldier_id, str(r.soldier_id)),
            from_node_id=r.from_node_id, to_node_id=r.to_node_id, status=r.status,
        )
        for r in reqs
    ]
```

Add `from sqlalchemy import select` to the imports if not already present (check the top of the file — it currently imports only `Session` from `sqlalchemy.orm`, not `select`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv\Scripts\python -m pytest tests/integration/test_hierarchy_transfers_api.py -v`
Expected: PASS, all tests in the file (the new one plus the 7 pre-existing ones — none of the existing assertions check for the *absence* of `soldier_name` so they remain green).

- [ ] **Step 5: Update the frontend type and rendering**

In `frontend/src/api/hierarchyTransfers.ts`, add the field:

```typescript
export interface TransferRequest {
  id: string;
  soldier_id: string;
  soldier_name: string;
  from_node_id: string | null;
  to_node_id: string;
  status: string;
}
```

In `frontend/src/pages/ApprovalsPage.tsx`, change line 805 from:

```tsx
<strong><SoldierLink id={req.soldier_id} name={req.soldier_id.slice(0, 8)} /></strong>
```

to:

```tsx
<strong><SoldierLink id={req.soldier_id} name={req.soldier_name} /></strong>
```

- [ ] **Step 6: Update existing fixtures and add a new test**

`frontend/src/pages/ApprovalsPage.test.tsx` already has a `describe("ApprovalsPage - transfers tab", ...)` block (lines 420-486) with two tests using inline `TransferRequest` fixtures at lines 423 and 455 (and their `approveTransferRequest`/`rejectTransferRequest` mock resolutions at 426 and 458). Once `soldier_name` becomes a required field on `TransferRequest` (Step 5), TypeScript will fail to compile these existing fixtures — add `soldier_name: "חייל בדיקה"` to all four fixture objects at lines 423, 426, 455, 458.

Then add a third test in the same `describe` block:

```tsx
it("shows the soldier's name, not a truncated id", async () => {
  vi.mocked(hierarchyTransfersApi.listPendingTransferRequests).mockResolvedValue([
    { id: "tr1", soldier_id: "sol-9", soldier_name: "דנה לוי", from_node_id: "n1", to_node_id: "n2", status: "pending" },
  ]);

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SoldierModalProvider>
          <ApprovalsPage />
        </SoldierModalProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );

  const transfersTab = await screen.findByTestId("approvals-tab-transfers");
  fireEvent.click(transfersTab);

  expect(await screen.findByText("דנה לוי")).toBeInTheDocument();
  expect(screen.queryByText("sol-9")).not.toBeInTheDocument();
});
```

- [ ] **Step 7: Run frontend test, lint, typecheck**

Run: `cd frontend && npx vitest run src/pages/ApprovalsPage.test.tsx`
Expected: PASS.
Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routes/hierarchy_transfers.py backend/tests/integration/test_hierarchy_transfers_api.py frontend/src/api/hierarchyTransfers.ts frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/ApprovalsPage.test.tsx
git commit -m "fix: show soldier name instead of truncated id on transfer requests"
```

---

## Task 2: Wrong-username login shows the real error, not "network error" (item 9)

**Files:**
- Modify: `frontend/src/pages/LoginPage.tsx:35-49`
- Test: `frontend/src/pages/LoginPage.test.tsx`

**Interfaces:**
- Consumes: existing `login.errors.invalid_credentials` i18n key (already in `frontend/src/i18n/he.json:16`, no new copy needed).
- Produces: nothing consumed by later tasks — this task is fully self-contained.

The backend's `LoginRequest.personal_number` field has a strict pattern `^[0-9]{7,8}$` (`backend/app/routes/auth.py:40`). A non-numeric or wrong-length personal number never reaches the login handler — FastAPI/Pydantic reject it with HTTP 422 before any 401 logic runs. `LoginPage.tsx`'s current catch block (lines 35-49) only special-cases 401 and 429; every other status, including 422, falls into `else setErrorKey("network")`, showing a generic network-error message for what is really a bad-username case.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/LoginPage.test.tsx`:

```tsx
function makeValidationError() {
  const err = new AxiosError("validation error");
  err.response = {
    status: 422,
    headers: {},
    data: { detail: [{ msg: "String should match pattern" }] },
    statusText: "Unprocessable Entity",
    // @ts-expect-error partial mock
    config: {},
  };
  return err;
}

test("shows the invalid-credentials message, not a generic network error, when the username fails validation", async () => {
  mockLogin.mockRejectedValueOnce(makeValidationError());
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  fireEvent.change(screen.getByTestId("personal-number-input"), { target: { value: "abc" } });
  fireEvent.change(screen.getByTestId("password-input"), { target: { value: "password" } });
  const form = screen.getByTestId("login-form");
  fireEvent.submit(form);
  await waitFor(() => {
    expect(screen.getByText("login.errors.invalid_credentials")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/LoginPage.test.tsx`
Expected: FAIL — the rendered error is `login.errors.network`, not `login.errors.invalid_credentials`.

- [ ] **Step 3: Fix the status-code mapping**

In `frontend/src/pages/LoginPage.tsx`, replace the `catch` block body (lines 36-49):

```tsx
if (err instanceof AxiosError) {
  if (err.response?.status === 401) {
    setErrorKey("invalid_credentials");
    const d = err.response.data?.detail;
    if (d && typeof d === "object" && "attempts" in d) {
      setAttempts({ n: d.attempts, max: d.max_attempts });
    }
  } else if (err.response?.status === 429) {
    setErrorKey("rate_limited");
    setRetryAfterSeconds(err.response.headers["retry-after"] ?? null);
  } else if (err.response && err.response.status >= 400 && err.response.status < 500) {
    // Any other 4xx (e.g. 422 field-validation failure on a malformed
    // personal number) is functionally a bad-credentials case from the
    // user's point of view — never surface it as a generic network error.
    setErrorKey("invalid_credentials");
  } else {
    setErrorKey("network");
  }
} else {
  setErrorKey("network");
}
```

Note the `attempts` block stays inside the `401` branch only — a 422 response has no `attempts`/`max_attempts` in its body, so don't try to read them there.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/LoginPage.test.tsx`
Expected: PASS, all tests in the file (3 total: rate-limited, attempts-remaining, new validation-error test).

- [ ] **Step 5: Lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx frontend/src/pages/LoginPage.test.tsx
git commit -m "fix: show invalid-credentials message instead of network error for malformed usernames"
```

---

## Task 3: Announcement unit picker renders a real hierarchy tree (item 10)

**Files:**
- Modify: `frontend/src/components/HierarchyNodePickerModal.tsx`
- Test: `frontend/src/components/HierarchyNodePickerModal.test.tsx` (new file)

**Interfaces:**
- Consumes: `NodeDTO` from `frontend/src/api/hierarchy.ts` (`fetchFullTree()` already returns nodes nested via `children?: NodeDTO[]`, no API change needed).
- Produces: nothing consumed elsewhere — `onPicked(nodeId: string, nodeName: string)` callback signature is unchanged, so `frontend/src/pages/AnnouncementsPage.tsx` (the only caller) needs no changes.

Currently `HierarchyNodePickerModal.tsx` calls `flatten()` on the tree from `fetchFullTree()` and renders every node as a flat list with no depth/indentation and no expand/collapse — a commander three levels deep looks identical to a top-level corps. Fix: render the already-nested `NodeDTO[]` recursively with depth-based indentation and expand/collapse, following the same visual pattern as `frontend/src/components/HierarchyCheckboxTree.tsx` (indent via `paddingRight: depth * 16 + 4`, expand toggle `▾`/`▸`, root rows start expanded) but with a "בחר" pick-button per row instead of a checkbox, and keep the existing search box (search still shows a flat filtered list — a tree layout doesn't make sense once you're filtering for a name).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/HierarchyNodePickerModal.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import HierarchyNodePickerModal from "./HierarchyNodePickerModal";
import * as hierarchyApi from "../api/hierarchy";

vi.mock("../api/hierarchy");

function tree() {
  return [
    {
      id: "root1", name: "אוגדה", level: "division", parent_id: null,
      commander_id: null, commander_name: null, path_ids: ["root1"],
      duty_managers: [], dm_manageable: false, can_edit: true,
      children: [
        {
          id: "child1", name: "יחידה א", level: "unit", parent_id: "root1",
          commander_id: null, commander_name: null, path_ids: ["root1", "child1"],
          duty_managers: [], dm_manageable: false, can_edit: true, children: [],
        },
      ],
    },
  ];
}

test("shows child nodes indented under their parent, collapsed by default below the root", async () => {
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue(tree());
  render(<HierarchyNodePickerModal onClose={vi.fn()} onPicked={vi.fn()} />);
  await waitFor(() => expect(screen.getByText("אוגדה")).toBeInTheDocument());
  expect(screen.queryByText("יחידה א")).not.toBeInTheDocument();
});

test("expanding the root reveals its child, and picking it calls onPicked with its id and name", async () => {
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue(tree());
  const onPicked = vi.fn();
  render(<HierarchyNodePickerModal onClose={vi.fn()} onPicked={onPicked} />);
  await waitFor(() => expect(screen.getByText("אוגדה")).toBeInTheDocument());
  fireEvent.click(screen.getByLabelText("הרחב"));
  expect(screen.getByText("יחידה א")).toBeInTheDocument();
  fireEvent.click(screen.getAllByText("בחר")[1]);
  expect(onPicked).toHaveBeenCalledWith("child1", "יחידה א");
});

test("typing a search term still filters across all depths", async () => {
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue(tree());
  render(<HierarchyNodePickerModal onClose={vi.fn()} onPicked={vi.fn()} />);
  await waitFor(() => expect(screen.getByText("אוגדה")).toBeInTheDocument());
  fireEvent.change(screen.getByPlaceholderText("חיפוש..."), { target: { value: "יחידה א" } });
  expect(screen.getByText("יחידה א")).toBeInTheDocument();
  expect(screen.queryByText("אוגדה")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HierarchyNodePickerModal.test.tsx`
Expected: FAIL — today's implementation renders every node flat, so `screen.getByText("יחידה א")` is already visible before expanding (first test fails), and there's no expand button (`getByLabelText("הרחב")` throws).

- [ ] **Step 3: Rewrite the component**

Replace `frontend/src/components/HierarchyNodePickerModal.tsx` in full:

```tsx
import { useEffect, useMemo, useState } from "react";
import { NodeDTO, fetchFullTree } from "../api/hierarchy";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  onClose: () => void;
  onPicked: (nodeId: string, nodeName: string) => void;
}

interface FlatNode {
  id: string;
  name: string;
  level: string;
}

function flatten(nodes: NodeDTO[]): FlatNode[] {
  const out: FlatNode[] = [];
  for (const n of nodes) {
    out.push({ id: n.id, name: n.name, level: n.level });
    if (n.children && n.children.length > 0) {
      out.push(...flatten(n.children));
    }
  }
  return out;
}

function TreeRow({
  node,
  depth,
  onPicked,
}: {
  node: NodeDTO;
  depth: number;
  onPicked: (nodeId: string, nodeName: string) => void;
}) {
  const hasChildren = (node.children?.length ?? 0) > 0;
  const [expanded, setExpanded] = useState(depth === 0);

  return (
    <div>
      <div
        className="flex items-center justify-between text-sm p-1.5 rounded hover:bg-gray-50 dark:hover:bg-gray-700"
        style={{ paddingRight: `${depth * 16 + 4}px` }}
      >
        <div className="flex items-center gap-1 min-w-0">
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-[10px] shrink-0"
            aria-label={expanded ? "כווץ" : "הרחב"}
          >
            {hasChildren ? (expanded ? "▾" : "▸") : ""}
          </button>
          <span className="dark:text-gray-100 truncate">{node.name}</span>
        </div>
        <button
          type="button"
          className="text-indigo-600 hover:underline text-xs shrink-0"
          onClick={() => onPicked(node.id, node.name)}
        >
          בחר
        </button>
      </div>
      {expanded && hasChildren && node.children!.map((child) => (
        <TreeRow key={child.id} node={child} depth={depth + 1} onPicked={onPicked} />
      ))}
    </div>
  );
}

export default function HierarchyNodePickerModal({ onClose, onPicked }: Props) {
  useModalBackClose(onClose);
  const [tree, setTree] = useState<NodeDTO[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchFullTree()
      .then(setTree)
      .catch(() => setError("שגיאה בטעינת רשימת היחידות"))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim();
    if (!q) return [];
    return flatten(tree).filter((n) => n.name.includes(q));
  }, [tree, search]);

  const searching = search.trim().length > 0;

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96 max-h-[80dvh] flex flex-col"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-semibold dark:text-gray-100">בחר יחידה</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        <input
          className="border rounded p-1.5 w-full mb-3 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 text-sm"
          placeholder="חיפוש..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        {error && <p className="text-red-500 text-xs mb-2">{error}</p>}
        {loading && <p className="text-gray-400 text-xs mb-2">טוען...</p>}

        <div className="overflow-y-auto flex-1 space-y-1">
          {searching ? (
            <>
              {filtered.map((n) => (
                <div
                  key={n.id}
                  className="flex items-center justify-between text-sm p-1.5 rounded hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <span className="dark:text-gray-100">{n.name}</span>
                  <button
                    type="button"
                    className="text-indigo-600 hover:underline text-xs"
                    onClick={() => onPicked(n.id, n.name)}
                  >
                    בחר
                  </button>
                </div>
              ))}
              {!loading && filtered.length === 0 && (
                <p className="text-gray-400 text-xs text-center py-4">לא נמצאו יחידות</p>
              )}
            </>
          ) : (
            <>
              {tree.map((n) => (
                <TreeRow key={n.id} node={n} depth={0} onPicked={onPicked} />
              ))}
              {!loading && tree.length === 0 && (
                <p className="text-gray-400 text-xs text-center py-4">לא נמצאו יחידות</p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/HierarchyNodePickerModal.test.tsx`
Expected: PASS, all 3 tests.

- [ ] **Step 5: Lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/HierarchyNodePickerModal.tsx frontend/src/components/HierarchyNodePickerModal.test.tsx
git commit -m "fix: render the announcement unit picker as an expandable tree, not a flat list"
```

---

## Task 4: Fix reversed-looking exemption/constraint/dismissal/call-up date ranges (item 15)

**Files:**
- Modify: `frontend/src/components/ExemptionsPanel.tsx:174-176, 224-226`
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx:663-665`
- Modify: `frontend/src/components/DutyHistoryPanel.tsx:176-186`
- Test: `frontend/src/components/ExemptionsPanel.test.tsx`
- Test: `frontend/src/components/UnifiedSoldierModal.test.tsx` (check first whether this file exists — if not, skip adding a UnifiedSoldierModal test and rely on the ExemptionsPanel + DutyHistoryPanel tests as the regression coverage for this bug class, noting so in the commit)
- Test: `frontend/src/components/DutyHistoryPanel.test.tsx` (check first whether it exists)

**Interfaces:**
- No new interfaces — purely a rendering fix.

**Root cause:** `formatDate()` (`frontend/src/utils/formatDate.ts:7-16`) returns digit-and-dot strings like `15.08.2026`. Digits are a "European Number" bidi class; dots between them are weak/neutral characters. When two such date strings are joined by an arrow (`→`) or dash and placed inside an **RTL** container *without* an explicit `dir="ltr"` on that span, the browser's Unicode bidi algorithm can re-order the two dates relative to each other, making a `start → end` range visually read as reversed. The codebase already has the correct pattern in several places — e.g. `frontend/src/pages/MyRequestsPage.tsx:227` (`<span dir="ltr" ...>{c.start_date} → {c.end_date}</span>`) and `frontend/src/pages/ApprovalsPage.tsx:460-461` — but three call sites were missed. This task finds and fixes those three (confirmed via a targeted repo-wide audit — see the note at the end of this task for how to re-verify no others were missed).

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/components/ExemptionsPanel.test.tsx` (the file already mocks `listExemptions` with an `ex2` fixture that has both `start_date: "2020-01-01"` and `end_date: "2020-01-10"` — reuse it):

```tsx
test("active exemption date range renders left-to-right regardless of page direction", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
  await waitFor(() => screen.getByTestId("exemption-row-ex1"));
  const row = screen.getByTestId("exemption-row-ex1");
  const dateLine = within(row).getByText(/01.01.2020/);
  expect(dateLine.closest("[dir='ltr']")).not.toBeNull();
});

test("past exemption date range renders left-to-right regardless of page direction", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
  await waitFor(() => screen.getByTestId("exemption-row-ex2"));
  const row = screen.getByTestId("exemption-row-ex2");
  const dateLine = within(row).getByText(/01.01.2020/);
  expect(dateLine.closest("[dir='ltr']")).not.toBeNull();
});
```

Note: both fixture exemptions have `start_date: "2020-01-01"` and are distinguished by whether `end_date` is set (`ex1` open-ended → "active" bucket, `ex2` closed 10-day range → also active since `2020-01-10` isn't in the past relative to... check `ExemptionsPanel.tsx`'s actual active/expired split logic before assuming which bucket each fixture lands in; if both land in the "active" list, adjust the mock to add a third exemption with `end_date` clearly in the past (e.g. `"2020-01-10"` alongside `today` being mocked/irrelevant — check how the component determines "today") so the past-bucket test has a real target. Read `ExemptionsPanel.tsx`'s `today`/filter logic (around where `expiredItems`/active split happens, module top) before writing this step's final assertion — the exact `data-testid` values (`exemption-row-ex1` etc.) come from the `id` field in the mock fixtures already in the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/ExemptionsPanel.test.tsx`
Expected: FAIL — `dateLine.closest("[dir='ltr']")` is `null` for both, since neither `<p>` wrapper at lines 174 and 224 currently sets `dir="ltr"`.

- [ ] **Step 3: Fix ExemptionsPanel.tsx**

At `frontend/src/components/ExemptionsPanel.tsx:174`, change:

```tsx
<p className="text-xs text-indigo-700 dark:text-indigo-300">
```

to:

```tsx
<p className="text-xs text-indigo-700 dark:text-indigo-300" dir="ltr">
```

At line 224, change:

```tsx
<span className="text-gray-500 dark:text-gray-400 text-xs">
```

to:

```tsx
<span className="text-gray-500 dark:text-gray-400 text-xs" dir="ltr">
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/ExemptionsPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Fix UnifiedSoldierModal.tsx**

At `frontend/src/components/UnifiedSoldierModal.tsx:664`, change:

```tsx
<span className="text-gray-500">{formatDate(c.start_date)} → {formatDate(c.end_date)}</span>
```

to:

```tsx
<span className="text-gray-500" dir="ltr">{formatDate(c.start_date)} → {formatDate(c.end_date)}</span>
```

If `frontend/src/components/UnifiedSoldierModal.test.tsx` exists (`Grep -n "constraint-row" frontend/src/components/UnifiedSoldierModal.test.tsx` first), add an equivalent assertion there (`expect(within(row).getByText(/→/).closest("[dir='ltr']")).not.toBeNull()`); otherwise this fix ships without a dedicated new test for this call site — that's acceptable, note it in the commit message.

- [ ] **Step 6: Fix DutyHistoryPanel.tsx**

At `frontend/src/components/DutyHistoryPanel.tsx:179`, change:

```tsx
<p className="text-xs text-gray-500">
```

to:

```tsx
<p className="text-xs text-gray-500" dir="ltr">
```

This is the shared date-range line for every event type in the timeline (`assignment`, `cancellation`, `dismissal`, `call_up`, `exemption`, `constraint`, `range_removed`) — fixing it here covers dismissal/call-up ranges, which have no other display path in the frontend.

If `frontend/src/components/DutyHistoryPanel.test.tsx` exists, add a test rendering a `dismissal` or `call_up` event with a multi-day range and asserting the date line's closest ancestor has `dir="ltr"`; otherwise document the gap in the commit message the same way as Step 5.

- [ ] **Step 7: Run the full frontend test suite for touched files**

Run: `cd frontend && npx vitest run src/components/ExemptionsPanel.test.tsx src/components/UnifiedSoldierModal.test.tsx src/components/DutyHistoryPanel.test.tsx`
(Vitest silently skips file args that don't exist — safe to include even if some weren't found in Steps 5/6.)
Expected: PASS.

- [ ] **Step 8: Re-verify no other exemption/constraint/dismissal/call-up date-range display is missing `dir="ltr"`**

Run these two searches and manually check every hit already has `dir="ltr"` on the same element or a close ancestor (the three fixed above, plus the already-correct ones in `MyRequestsPage.tsx`, `ApprovalsPage.tsx`, `ExemptionsPanel.tsx:268`, are the full known set as of this plan being written — but re-run rather than trusting this list, in case other work landed on `dev` in the meantime):

```bash
grep -rn "start_date.*→\|start_date.*–" frontend/src --include=*.tsx
grep -rn "formatDate(.*start" frontend/src --include=*.tsx
```

Fix any newly-discovered instance the same way (add `dir="ltr"` to the nearest wrapping element), following the same TDD steps.

- [ ] **Step 9: Lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/ExemptionsPanel.tsx frontend/src/components/ExemptionsPanel.test.tsx frontend/src/components/UnifiedSoldierModal.tsx frontend/src/components/DutyHistoryPanel.tsx
git commit -m "fix: force left-to-right rendering on exemption/constraint/dismissal/call-up date ranges"
```

(Add any test files touched in Steps 5/6 to the `git add` if they exist.)

---

## Task 5: Registration-flow date fields — verify and cover typed input (item 3)

**Files:**
- Modify: `frontend/src/pages/RegisterPage.tsx:419-424, 528-533`
- Verify (no changes expected): `frontend/src/components/DateInput.test.tsx`, `frontend/src/pages/RegisterPage.test.tsx`

**Interfaces:**
- No new interfaces.

**Investigation note (read before starting):** `frontend/src/components/DateInput.tsx` already implements full typed-`dd/mm/yyyy` parsing with commit-on-6-or-8-digits (added in commit `d9690957`, 2026-07-24, well before this batch's spec was written), and `frontend/src/components/DateInput.test.tsx` already has 4 passing tests covering typed input end-to-end, including the two-digit-year and backspace-mid-type cases. `RegisterPage.tsx`'s exemption (lines 419-424) and personal-constraint (lines 528-533) date rows already pass their `DateInput`s a controlled `value` and an `onChange` that updates form state — the same wiring pattern used everywhere else `DateInput` is used successfully (e.g. `frontend/src/pages/MyRequestsPage.tsx`, whose `DateInput` usage is already covered indirectly by that page's own tests).

Driving the full 6-step registration wizard in a test (invite code → personal info incl. rank Combobox, gender select, 4 required dates, password strength → exemptions → constraints) to reach step 4 is expensive and fragile for what the investigation shows is very likely already-correct wiring — `RegisterPage.tsx`'s `step2Invalid` alone (line 248-252) requires ~10 fields including a fuzzy-search rank Combobox. That cost isn't justified for a "quick fix" batch item where the component-level fix already shipped weeks ago. Scope this task down to: (a) the `data-testid` additions below, so these fields are targetable in any *future* test without hunting for placeholder text, and (b) confirming the existing `DateInput.test.tsx` coverage plus a manual browser check (final verification section) are the actual guardrails — not a new heavyweight wizard test. If manual browser verification in the Final Verification section below turns up an actual repro, escalate: that means the investigation note's premise was wrong, and a fresh test targeted at the *specific* failing interaction (not a full wizard walkthrough) should be added at that point.

- [ ] **Step 1: Add `data-testid` to the constraint and exemption date fields**

In `frontend/src/pages/RegisterPage.tsx`, at lines 419-424 (exemption request dates), add test ids:

```tsx
<DateInput className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={er.permanent ? "" : er.start_date}
  max={er.end_date || undefined} disabled={er.permanent}
  data-testid={`register-er-start-${i}`}
  onChange={iso => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], start_date: iso}; set("exemption_requests", rows); }} />
<DateInput className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={er.permanent ? "" : er.end_date}
  min={er.start_date || undefined} disabled={er.permanent}
  data-testid={`register-er-end-${i}`}
  onChange={iso => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], end_date: iso}; set("exemption_requests", rows); }} />
```

At lines 528-533 (personal constraint dates):

```tsx
<DateInput className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={pc.start_date}
  max={pc.end_date || undefined}
  data-testid={`register-pc-start-${i}`}
  onChange={iso => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], start_date: iso}; set("personal_constraints", rows); }} />
<DateInput className="block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={pc.end_date}
  min={pc.start_date || undefined}
  data-testid={`register-pc-end-${i}`}
  onChange={iso => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], end_date: iso}; set("personal_constraints", rows); }} />
```

- [ ] **Step 2: Run the existing DateInput and RegisterPage suites to confirm current state**

Run: `cd frontend && npx vitest run src/components/DateInput.test.tsx src/pages/RegisterPage.test.tsx`
Expected: PASS — this is a baseline confirmation, not a new failing test. `DateInput.test.tsx`'s 4 tests already exercise the exact typed-digit-commit behavior `RegisterPage.tsx` depends on; `RegisterPage.test.tsx` should still pass unchanged after Step 1's `data-testid` additions (they're purely additive props, no behavior change).

- [ ] **Step 3: Lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/RegisterPage.tsx
git commit -m "chore: add data-testid to registration date fields for future test targeting"
```

---

## Final verification (after all 5 tasks)

- [ ] Run the full backend fast suite: `cd backend && .venv\Scripts\python -m pytest -q`
- [ ] Run the full frontend suite: `cd frontend && npm test`
- [ ] Run `cd frontend && npm run lint && npm run typecheck`
- [ ] Run `cd backend && .venv\Scripts\python -m ruff check . && .venv\Scripts\python -m mypy app`
- [ ] Manually smoke-test in the browser per the `run` skill / dev.ps1: log in with a malformed username (expect Hebrew invalid-credentials message), open a pending transfer request in Approvals (expect a real name), open the announcement composer's unit picker (expect an expandable tree), view a soldier's exemptions/constraints (expect date ranges read left-to-right).
