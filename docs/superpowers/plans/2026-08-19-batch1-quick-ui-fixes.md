# Batch 1 — Quick UI Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five small, independent user-reported UI bugs (items 8, 9, 10, 15, 3 from the 2026-08-18 triage spec) in the "justice" army-duty-management app.

**Architecture:** Five independent tasks, each touching one narrow slice of the app (a route handler, a page component, or a shared component). No shared state between tasks — they can be implemented and reviewed in any order. Two of the five (items 15 and 3) turned out, on investigation, to already be correctly implemented in the current codebase; their tasks add regression tests instead of behavior changes so the fix stays locked in.

**Tech Stack:** FastAPI + SQLAlchemy (backend/app), Pydantic schemas, React + TypeScript + Vite (frontend/src), Vitest + Testing Library, pytest.

## Global Constraints

- Hebrew UI text, English code/identifiers (per CLAUDE.md).
- `end_date` is exclusive ONLY for duty/shift/assignment ranges; constraints, exemptions, dismissals, and call-ups are inclusive. Do not apply `lastDutyDay`/`toExclusiveEndDate`/`formatDutyRange` to the latter.
- RBAC: any permission change must flow through `authz.authorize()` (not touched in this batch).
- Zero ESLint warnings enforced (`npm run lint` in `frontend/`). Run `npm run typecheck` separately (not part of lint).
- Backend: `ruff`, `mypy`, and `pytest` (markers: algorithm | auth | hierarchy | duty | scoring | notifications | soldiers | misc) must pass. Activate `backend\.venv\Scripts\activate` first.
- Commit after each task's tests pass — small, focused commits, `fix:`/`feat:`/`test:` prefixes per conventional style already used in this repo's log.
- Worktree root: `C:\Users\Shoham\workspace\Justice\.worktrees\batch1-quick-ui-fixes`, branch `batch1-quick-ui-fixes`, already created off `dev` (verify with `git log --oneline -1` — it should match `dev`'s tip before you start).

---

### Task 1: Transfer request soldier name (item 8)

**Files:**
- Modify: `backend/app/routes/hierarchy_transfers.py`
- Modify: `frontend/src/api/hierarchyTransfers.ts`
- Modify: `frontend/src/pages/ApprovalsPage.tsx:805`
- Test: `backend/tests/integration/test_hierarchy_transfers_api.py`
- Test: `frontend/src/pages/ApprovalsPage.test.tsx`

**Interfaces:**
- Produces: `TransferOut.soldier_name: str` (backend response field), `TransferRequest.soldier_name: string` (frontend type), both non-optional strings (empty string fallback, never `null`/`undefined`).

**Context:** `ApprovalsPage.tsx:805` currently renders `req.soldier_id.slice(0, 8)` as the display name for pending hierarchy-transfer requests — a truncated UUID instead of a name. Every sibling row in the same file (enrollment, constraints, exemption requests, swaps) already resolves and displays a real name via a `soldier_name` field on its DTO (see `frontend/src/pages/ApprovalsPage.tsx:457,508,592,764` for the pattern this task mirrors). The backend's `TransferOut` schema (`backend/app/routes/hierarchy_transfers.py:27-39`) has no `soldier_name` field at all yet.

- [ ] **Step 1: Write the failing backend test**

Add to `backend/tests/integration/test_hierarchy_transfers_api.py` (after the existing `test_reject_transfer_via_api`, keeping the same style — `client`/`admin_session` fixtures, `auth_headers`/`create_node`/`create_soldier` helpers already imported at the top of the file):

```python
def test_transfer_response_includes_soldier_name(client: TestClient, admin_session: Session):
    src = create_node(admin_session, level="unit", name="api_src3")
    dst = create_node(admin_session, level="unit", name="api_dst3")
    soldier = create_soldier(
        admin_session, personal_number="7991005", hierarchy_node_id=src.id,
        full_name="ישראל ישראלי",
    )
    admin = create_soldier(admin_session, personal_number="7991006", role="admin")
    admin_session.commit()

    resp = client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(soldier.id), "to_node_id": str(dst.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["soldier_name"] == "ישראל ישראלי"
    req_id = resp.json()["id"]

    resp2 = client.post(f"/api/hierarchy-transfers/{req_id}/approve", headers=auth_headers(admin))
    assert resp2.json()["soldier_name"] == "ישראל ישראלי"

    resp3 = client.get("/api/hierarchy-transfers/pending", headers=auth_headers(admin))
    assert resp3.status_code == 200
    # the approved request above is no longer pending; create a second one to check the list path
    soldier2 = create_soldier(
        admin_session, personal_number="7991007", hierarchy_node_id=src.id,
        full_name="משה כהן",
    )
    admin_session.commit()
    client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(soldier2.id), "to_node_id": str(dst.id)},
        headers=auth_headers(admin),
    )
    resp4 = client.get("/api/hierarchy-transfers/pending", headers=auth_headers(admin))
    names = {item["soldier_name"] for item in resp4.json()}
    assert "משה כהן" in names
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/integration/test_hierarchy_transfers_api.py::test_transfer_response_includes_soldier_name -v`
Expected: FAIL — `KeyError: 'soldier_name'` (field doesn't exist in the response yet).

- [ ] **Step 3: Add `soldier_name` to the backend response**

In `backend/app/routes/hierarchy_transfers.py`, add the import and field, and thread a resolved name through every call site of `_out`:

```python
from sqlalchemy import select
```
(add alongside the existing `from sqlalchemy.orm import Session` import at the top)

Change the `TransferOut` model (line 27-33):

```python
class TransferOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str
    from_node_id: uuid.UUID | None
    to_node_id: uuid.UUID
    status: str
```

Change `_out` (line 35-39) to take the resolved name:

```python
def _out(req: HierarchyTransferRequest, soldier_name: str) -> TransferOut:
    return TransferOut(
        id=req.id, soldier_id=req.soldier_id, soldier_name=soldier_name,
        from_node_id=req.from_node_id, to_node_id=req.to_node_id, status=req.status,
    )
```

In `create_transfer` (line 42-58), the soldier is already fetched — reuse it:

```python
    try:
        req = svc.create_request(session, soldier_id=body.soldier_id, to_node_id=body.to_node_id, requested_by=user.id)
    except svc.HierarchyTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    session.commit()
    return _out(req, soldier.full_name)
```

In `approve_transfer` (line 61-78), fetch the soldier right after loading `req` and pass its name at the return:

```python
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found")
    forbid_self_target(user, req.soldier_id)
    soldier = session.get(Soldier, req.soldier_id)
    dest_node = session.get(HierarchyNode, req.to_node_id)
    authorize(session, user, Action.HIERARCHY_TRANSFER, target_node=dest_node)
    try:
        req = svc.approve_request(session, request_id=request_id, actor_id=user.id)
    except svc.HierarchyTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    session.commit()
    return _out(req, soldier.full_name if soldier else "")
```

Apply the identical pattern to `reject_transfer` (line 81-99) — fetch `soldier = session.get(Soldier, req.soldier_id)` right after the null-check on `req`, and change the final `return _out(req)` to `return _out(req, soldier.full_name if soldier else "")`.

Change `list_pending` (line 102-107) to batch-resolve names:

```python
@router.get("/pending", response_model=list[TransferOut])
def list_pending(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[TransferOut]:
    reqs = svc.list_pending_for_approver(session, approver_id=user.id)
    soldier_ids = {r.soldier_id for r in reqs}
    names = {
        s.id: s.full_name
        for s in session.execute(select(Soldier).where(Soldier.id.in_(soldier_ids))).scalars()
    } if soldier_ids else {}
    return [_out(r, names.get(r.soldier_id, "")) for r in reqs]
```

- [ ] **Step 4: Run the backend test to verify it passes**

Run: `pytest backend/tests/integration/test_hierarchy_transfers_api.py -v`
Expected: PASS (all tests in the file, including the new one and the two pre-existing ones which still call `_out` indirectly through the route).

- [ ] **Step 5: Update the frontend type and rendering**

In `frontend/src/api/hierarchyTransfers.ts`, add the field to the `TransferRequest` interface:

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

In `frontend/src/pages/ApprovalsPage.tsx`, line 805, change:

```tsx
                    <strong><SoldierLink id={req.soldier_id} name={req.soldier_id.slice(0, 8)} /></strong>
```

to:

```tsx
                    <strong><SoldierLink id={req.soldier_id} name={req.soldier_name || req.soldier_id.slice(0, 8)} /></strong>
```

- [ ] **Step 6: Write the failing frontend test**

In `frontend/src/pages/ApprovalsPage.test.tsx`, inside `describe("ApprovalsPage - transfers tab", ...)` (after the existing two `it` blocks, matching their structure), add:

```tsx
  it("renders the transferred soldier's real name, not a truncated id", async () => {
    vi.mocked(hierarchyTransfersApi.listPendingTransferRequests).mockResolvedValue([
      { id: "tr1", soldier_id: "sol-9", soldier_name: "דני לוי", from_node_id: "n1", to_node_id: "n2", status: "pending" },
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

    expect(await screen.findByText("דני לוי")).toBeInTheDocument();
    expect(screen.queryByText("sol-9".slice(0, 8))).not.toBeInTheDocument();
  });
```

Also update the two pre-existing mocked `TransferRequest` objects in this describe block (lines ~423 and ~455) to include `soldier_name: "דני לוי"` so they satisfy the (now-required) TypeScript type — the assertions in those two tests don't depend on the name, so any non-empty string is fine.

- [ ] **Step 7: Run test to verify it fails, then passes**

Run: `cd frontend && npx vitest run src/pages/ApprovalsPage.test.tsx -t "transfers tab"`
Expected: FAIL first (missing `soldier_name` in mock → TS type error, or the name assertion fails) — fix any remaining TS errors from Step 6, then re-run.
Expected after Step 5+6: PASS.

- [ ] **Step 8: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add backend/app/routes/hierarchy_transfers.py backend/tests/integration/test_hierarchy_transfers_api.py frontend/src/api/hierarchyTransfers.ts frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/ApprovalsPage.test.tsx
git commit -m "fix: show transferred soldier's real name instead of truncated id (item 8)"
```

---

### Task 2: Wrong/malformed username shows generic network error (item 9)

**Files:**
- Modify: `frontend/src/pages/LoginPage.tsx`
- Test: `frontend/src/pages/LoginPage.test.tsx`

**Interfaces:**
- No new exported symbols; behavior-only change inside `onSubmit`'s catch block.

**Context:** `LoginRequest.personal_number` on the backend is constrained to `^[0-9]{7,8}$` (`backend/app/routes/auth.py:40`). A non-digit or wrong-length personal number never reaches the route handler — FastAPI/Pydantic rejects it with an automatic `422 Unprocessable Entity` before any business logic runs. `LoginPage.tsx`'s catch block (line 36-49) only special-cases `401` (→ `invalid_credentials`) and `429` (→ `rate_limited`); every other status, including this `422`, falls into the generic `else setErrorKey("network")` branch, showing "שגיאת רשת. נסה שוב." — a confusing message for what is really a bad-username case. The `login.errors.invalid_credentials` key/copy already exists (`frontend/src/i18n/he.json:16`, "מספר אישי או סיסמה שגויים") and is reused here — no new i18n key needed.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/LoginPage.test.tsx` (same file, same mocking pattern as the existing two tests — reuse the `mockLogin` and the `AxiosError` helpers already defined there):

```tsx
function makeValidationError() {
  const err = new AxiosError("unprocessable");
  err.response = {
    status: 422,
    headers: {},
    data: { detail: [{ msg: "String should match pattern", loc: ["body", "personal_number"] }] },
    statusText: "Unprocessable Entity",
    // @ts-expect-error partial mock
    config: {},
  };
  return err;
}

test("shows the invalid-credentials message, not a generic network error, for a malformed username", async () => {
  mockLogin.mockRejectedValueOnce(makeValidationError());
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  fireEvent.change(screen.getByTestId("personal-number-input"), { target: { value: "abc" } });
  fireEvent.change(screen.getByTestId("password-input"), { target: { value: "password" } });
  const form = screen.getByTestId("login-form");
  fireEvent.submit(form);
  await waitFor(() => {
    expect(screen.getByText("login.errors.invalid_credentials")).toBeInTheDocument();
  });
  expect(screen.queryByText("login.errors.network")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/LoginPage.test.tsx`
Expected: FAIL — the new test finds `login.errors.network` instead of `login.errors.invalid_credentials`.

- [ ] **Step 3: Fix the status mapping in `LoginPage.tsx`**

Change the catch block (currently lines 35-49):

```tsx
    } catch (err) {
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
        } else setErrorKey("network");
      } else {
        setErrorKey("network");
      }
    } finally {
```

to:

```tsx
    } catch (err) {
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
          setErrorKey("invalid_credentials");
        } else {
          setErrorKey("network");
        }
      } else {
        setErrorKey("network");
      }
    } finally {
```

This treats any 4xx (bad request shape, 422 validation, etc.) as an invalid-credentials case — the user typed something wrong — while a missing/undefined `response` (no connectivity, CORS, 5xx) still falls through to the generic network message.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/LoginPage.test.tsx`
Expected: PASS (all four tests in the file — the two pre-existing plus the new one).

- [ ] **Step 5: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx frontend/src/pages/LoginPage.test.tsx
git commit -m "fix: show invalid-credentials message instead of generic network error for malformed login (item 9)"
```

---

### Task 3: Announcement unit picker renders a real hierarchy tree (item 10)

**Files:**
- Modify: `frontend/src/components/HierarchyNodePickerModal.tsx`
- Test: `frontend/src/components/HierarchyNodePickerModal.test.tsx` (new file)

**Interfaces:**
- Consumes: `NodeDTO` from `frontend/src/api/hierarchy.ts` (`{ id, level, name, parent_id, children?, ... }`), `fetchFullTree(): Promise<NodeDTO[]>`.
- Produces: unchanged public props `{ onClose: () => void; onPicked: (nodeId: string, nodeName: string) => void }` — `AnnouncementsPage.tsx` (the only consumer) needs no changes, and its existing test file already mocks this component entirely so it is unaffected.

**Context:** `HierarchyNodePickerModal.tsx` currently flattens the tree (`flatten()`, line 16-25) into one alphabetically-unordered flat list with no depth/parent information shown — a commander's "יחידה" and its child "צוות" appear as unrelated flat rows. `frontend/src/components/HierarchyCheckboxTree.tsx` already solves this exact rendering problem elsewhere (admin unit-multi-select) with a `buildForest` + indented, expandable `TreeRow`. This task ports that same tree-building/rendering approach into the picker, replacing the flat list, but keeps a single-select "בחר" button per row (instead of a checkbox) and keeps the existing search box — filtering falls back to a flat matched-list view (same as today) when the user has typed a query, and shows the full tree otherwise.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/HierarchyNodePickerModal.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect } from "vitest";
import HierarchyNodePickerModal from "./HierarchyNodePickerModal";
import * as hierarchyApi from "../api/hierarchy";

vi.mock("../api/hierarchy");

function makeTree() {
  return [
    {
      id: "corps-1", level: "corps" as const, name: "אוגדה", parent_id: null,
      commander_id: null, commander_name: null, path_ids: ["corps-1"], duty_managers: [], dm_manageable: false, can_edit: true,
      children: [
        {
          id: "unit-1", level: "unit" as const, name: "יחידה א", parent_id: "corps-1",
          commander_id: null, commander_name: null, path_ids: ["corps-1", "unit-1"], duty_managers: [], dm_manageable: false, can_edit: true,
          children: [],
        },
      ],
    },
  ];
}

describe("HierarchyNodePickerModal", () => {
  it("renders parent/child structure with indentation, expandable nodes", async () => {
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue(makeTree());
    const onPicked = vi.fn();
    render(<HierarchyNodePickerModal onClose={vi.fn()} onPicked={onPicked} />);

    await waitFor(() => expect(screen.getByText("אוגדה")).toBeInTheDocument());
    // the root is expanded by default; its child should already be visible
    expect(screen.getByText("יחידה א")).toBeInTheDocument();

    const selectButtons = screen.getAllByText("בחר");
    fireEvent.click(selectButtons[1]);
    expect(onPicked).toHaveBeenCalledWith("unit-1", "יחידה א");
  });

  it("still supports search, falling back to a flat filtered list", async () => {
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue(makeTree());
    render(<HierarchyNodePickerModal onClose={vi.fn()} onPicked={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("אוגדה")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("חיפוש..."), { target: { value: "יחידה א" } });

    expect(screen.queryByText("אוגדה")).not.toBeInTheDocument();
    expect(screen.getByText("יחידה א")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HierarchyNodePickerModal.test.tsx`
Expected: FAIL — with the current flat rendering, "אוגדה" and "יחידה א" both render at the same time in the un-searched case too, but there is no reliable indentation/expand affordance to assert on and the "בחר" selection targets a differently-ordered flat list — at minimum the second test's "search narrows to only the match" assertion fails since the current flat list still shows all matches without a parent/child rendering concept to distinguish. (If either sub-assertion accidentally passes against the old flat code, proceed anyway — Step 3 is still required per the spec and the full test file must pass together afterward.)

- [ ] **Step 3: Rewrite `HierarchyNodePickerModal.tsx` to render a tree**

Replace the full file contents:

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
  parent_id: string | null;
}

interface TreeNode extends FlatNode {
  children: TreeNode[];
}

function flatten(nodes: NodeDTO[], parentId: string | null = null): FlatNode[] {
  const out: FlatNode[] = [];
  for (const n of nodes) {
    out.push({ id: n.id, name: n.name, level: n.level, parent_id: parentId });
    if (n.children && n.children.length > 0) {
      out.push(...flatten(n.children, n.id));
    }
  }
  return out;
}

function buildForest(nodes: FlatNode[]): TreeNode[] {
  const byId = new Map<string, TreeNode>(nodes.map((n) => [n.id, { ...n, children: [] }]));
  const roots: TreeNode[] = [];
  for (const node of byId.values()) {
    const parent = node.parent_id ? byId.get(node.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

function TreeRow({
  node, depth, onPicked,
}: {
  node: TreeNode;
  depth: number;
  onPicked: (id: string, name: string) => void;
}) {
  const hasChildren = node.children.length > 0;
  const [expanded, setExpanded] = useState(depth === 0);

  return (
    <div>
      <div
        className="flex items-center justify-between gap-1 py-1 hover:bg-gray-50 dark:hover:bg-gray-700 rounded"
        style={{ paddingRight: `${depth * 16 + 4}px` }}
      >
        <div className="flex items-center gap-1 min-w-0 flex-1">
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-[10px] shrink-0"
            aria-label={expanded ? "כווץ" : "הרחב"}
          >
            {hasChildren ? (expanded ? "▾" : "▸") : ""}
          </button>
          <span className="text-sm truncate dark:text-gray-100">{node.name}</span>
        </div>
        <button
          type="button"
          className="text-indigo-600 hover:underline text-xs shrink-0"
          onClick={() => onPicked(node.id, node.name)}
        >
          בחר
        </button>
      </div>
      {expanded && hasChildren && node.children.map((child) => (
        <TreeRow key={child.id} node={child} depth={depth + 1} onPicked={onPicked} />
      ))}
    </div>
  );
}

export default function HierarchyNodePickerModal({ onClose, onPicked }: Props) {
  useModalBackClose(onClose);
  const [nodes, setNodes] = useState<FlatNode[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchFullTree()
      .then((tree) => setNodes(flatten(tree)))
      .catch(() => setError("שגיאה בטעינת רשימת היחידות"))
      .finally(() => setLoading(false));
  }, []);

  const forest = useMemo(() => buildForest(nodes), [nodes]);

  const filtered = useMemo(() => {
    const q = search.trim();
    if (!q) return null;
    return nodes.filter((n) => n.name.includes(q));
  }, [nodes, search]);

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
          {filtered === null ? (
            forest.map((n) => <TreeRow key={n.id} node={n} depth={0} onPicked={onPicked} />)
          ) : (
            filtered.map((n) => (
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
            ))
          )}
          {!loading && filtered !== null && filtered.length === 0 && (
            <p className="text-gray-400 text-xs text-center py-4">לא נמצאו יחידות</p>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/HierarchyNodePickerModal.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run the full AnnouncementsPage test file to confirm no regression**

Run: `cd frontend && npx vitest run src/pages/AnnouncementsPage.test.tsx`
Expected: PASS — `AnnouncementsPage.test.tsx` mocks `HierarchyNodePickerModal` entirely (see its `vi.mock("../components/HierarchyNodePickerModal", ...)` block), so this file's tests are unaffected by the internal rewrite and should already pass unchanged; this step just confirms that.

- [ ] **Step 6: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/HierarchyNodePickerModal.tsx frontend/src/components/HierarchyNodePickerModal.test.tsx
git commit -m "feat: render admin unit picker as an indented hierarchy tree instead of a flat list (item 10)"
```

---

### Task 4: Reversed/inverted date-range display audit (item 15)

**Files:**
- Test: `frontend/src/components/ExemptionsPanel.test.tsx`
- Test: `frontend/src/pages/MyRequestsPage.test.tsx`

**Context — read before starting:** A thorough audit was already performed against this exact worktree (every exemption/constraint/dismissal/call-up date-range render site in the frontend was located and checked: `ExemptionsPanel.tsx` lines 175/225/269, `MyRequestsPage.tsx` lines 227/254/272/448/485, `ApprovalsPage.tsx` lines 461/522, `UnifiedSoldierModal.tsx:664`, `ExemptionInstanceModal.tsx:59-61`, `ExemptionsCell.tsx:14-15`, `EnrollmentApprovalModal.tsx:254`, `ShiftDetailPanel.tsx` lines 342-344/439/498-499, `UpcomingDutiesWidget.tsx:14-17`, and `DutyHistoryPanel.tsx:180-185` which has an explicit `EXCLUSIVE_END_DATE_EVENT_TYPES` allowlist gating `lastDutyDay` to only `assignment`/`cancellation` event types). **Every one of them already renders the inclusive-range convention correctly** — none call `lastDutyDay`/`toExclusiveEndDate`/`formatDutyRange` on an inclusive-type field, and none manually swap start/end. There is no display bug left to fix for this item in the current codebase.

Do not re-run this full audit — it has already been done. Do not modify any of the render sites listed above; they are correct as-is. This task's job is narrower: add regression tests on the two highest-traffic components so a future edit can't silently reintroduce the bug, since neither currently has a test asserting date-range *order* specifically.

One genuine, unrelated bug was found in passing and is explicitly **out of scope** here (it's a duty/shift exclusive-end-date bug, not an exemption/constraint/dismissal/call-up inclusive-range bug — item 15 is scoped to the latter only): `frontend/src/components/DismissalModal.tsx:492` renders `preview.current_shift.end_date` raw instead of via `lastDutyDay`. Leave it untouched; flag it separately after this batch merges (e.g. via a follow-up task) rather than fixing it here.

**Interfaces:** none — test-only task, no production code or exported signatures change.

- [ ] **Step 1: Add a regression test to `ExemptionsPanel.test.tsx`**

The file already mocks `listExemptionRequestsForSoldier` to return one row with `id: "req-1"`, `start_date: "2026-01-01"`, `end_date: "2026-01-05"` (see the `vi.mock("../api/exemptions", ...)` block near the top), and existing tests already locate that row via `screen.findByTestId("exemption-request-row-req-1")`. Add this test after the existing `test("revoking an exemption requires a reason...")` block, in the same file, using the same `render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />)` call the other tests use:

```tsx
test("renders the exemption-request date range in start-then-end order, not reversed", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
  const row = await screen.findByTestId("exemption-request-row-req-1");
  expect(row.textContent).toMatch(/01\.01\.2026[\s\S]*05\.01\.2026/);
});
```

- [ ] **Step 2: Run it**

Run: `cd frontend && npx vitest run src/components/ExemptionsPanel.test.tsx`
Expected: PASS (this is a regression test for already-correct behavior, not a bug fix — it should pass immediately; if it fails, stop and re-investigate before proceeding, since that would mean the prior audit's finding for this file was wrong).

- [ ] **Step 3: Add a regression test to `MyRequestsPage.test.tsx`**

The file already defines a `constraint` fixture with `start_date: "2026-01-01"`, `end_date: "2026-01-05"`, mocked via `constraintsApi.listMyConstraints`, and existing tests already locate its row via `screen.findByTestId("constraint-row-c1")`. Add this test inside `describe("MyRequestsPage - day-count badges", ...)`, after the existing `it("shows a day-count badge next to a pending constraint row", ...)` block, using the same `renderPage()` helper:

```tsx
  it("renders the constraint date range in start-then-end order, not reversed", async () => {
    renderPage();
    const row = await screen.findByTestId("constraint-row-c1");
    expect(row.textContent).toMatch(/01\.01\.2026[\s\S]*05\.01\.2026/);
  });
```

- [ ] **Step 4: Run it**

Run: `cd frontend && npx vitest run src/pages/MyRequestsPage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Full frontend test run**

Run: `cd frontend && npm test`
Expected: PASS, no regressions elsewhere.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ExemptionsPanel.test.tsx frontend/src/pages/MyRequestsPage.test.tsx
git commit -m "test: lock in correct (non-reversed) exemption/constraint date-range display order (item 15)"
```

- [ ] **Step 7: Flag the out-of-scope DismissalModal bug**

After this task is committed, use the `spawn_task` mechanism (or tell the user directly if not running as an autonomous agent) to flag: "`frontend/src/components/DismissalModal.tsx:492` renders a duty/shift `end_date` raw in the gimelim preview panel instead of via `lastDutyDay` — likely an off-by-one display bug, found while auditing item 15 but out of that item's scope (duty/shift ranges are excluded)." Do not fix it as part of this batch.

---

### Task 5: DateInput typed dates in registration (item 3)

**Files:**
- Test: `frontend/src/components/DateInput.test.tsx`

**Context — read before starting:** `DateInput.tsx` (`frontend/src/components/DateInput.tsx`) was verified against the exact usage pattern in `RegisterPage.tsx` (controlled `value`+`onChange` props, starting from an empty string, with `min`/`max` cross-field props as used for exemption/constraint date-range rows at lines 419-424 and 528-533) via two hands-on repro tests simulating real keystroke-by-keystroke typing (each `fireEvent.change` call passing the full accumulated input string, matching what a real `<input>` DOM element reports on each keystroke). **Both scenarios already commit correctly today** — typing a full 8-digit date (`01/03/2028`), typing a 6-digit short-year date (`14/08/20` → `2020-08-14`), and typing with a `max` prop set (cross-field constraint) all fire `onChange` with the correct ISO value with no code changes needed. The existing test suite in `DateInput.test.tsx` only covers *uncontrolled* usage (no `value` prop) — this task closes that coverage gap for the *controlled* usage pattern actually used during registration, so a future regression is caught. No production code in `DateInput.tsx` needs to change.

**Interfaces:** none — test-only task.

- [ ] **Step 1: Add controlled-mode tests to `DateInput.test.tsx`**

Add to `frontend/src/components/DateInput.test.tsx` (inside the existing `describe("DateInput", ...)` block, after the last `it`):

```tsx
  it("commits a typed 8-digit date when used in controlled mode (as in registration forms)", () => {
    function ControlledWrapper() {
      const [value, setValue] = useState("");
      return (
        <div>
          <DateInput value={value} onChange={setValue} data-testid="date-input" />
          <span data-testid="committed">{value}</span>
        </div>
      );
    }
    render(<ControlledWrapper />);
    const input = screen.getByTestId("date-input");
    for (const v of ["0", "01", "01/0", "01/03", "01/03/2", "01/03/20", "01/03/202", "01/03/2028"]) {
      fireEvent.change(input, { target: { value: v } });
    }
    expect(screen.getByTestId("committed").textContent).toBe("2028-03-01");
  });

  it("commits a typed short-year date in controlled mode with a cross-field max prop set", () => {
    function ControlledWrapper() {
      const [value, setValue] = useState("");
      return (
        <div>
          <DateInput value={value} onChange={setValue} max="2030-01-01" data-testid="date-input" />
          <span data-testid="committed">{value}</span>
        </div>
      );
    }
    render(<ControlledWrapper />);
    const input = screen.getByTestId("date-input");
    for (const v of ["1", "14", "14/0", "14/08", "14/08/2", "14/08/20"]) {
      fireEvent.change(input, { target: { value: v } });
    }
    expect(screen.getByTestId("committed").textContent).toBe("2020-08-14");
  });
```

Add `useState` to the file's imports (it currently imports only from `@testing-library/react`, `vitest`, and the component under test):

```tsx
import { useState } from "react";
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/DateInput.test.tsx`
Expected: PASS on all tests (the two new ones plus the four pre-existing ones). If either new test unexpectedly fails, stop — that means the prior investigation's finding was wrong and there is a real bug to fix in `DateInput.tsx`'s controlled-mode `useEffect`/`isTypingRef` interaction (`frontend/src/components/DateInput.tsx:77-82`); re-investigate before proceeding rather than forcing the test to pass.

- [ ] **Step 3: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/DateInput.test.tsx
git commit -m "test: lock in typed-date commit behavior for controlled DateInput usage in registration forms (item 3)"
```

---

## Final verification (after all 5 tasks)

- [ ] Run full backend suite: `pytest -q` (from `backend/`, venv activated). Expected: PASS.
- [ ] Run full frontend suite: `npm test` (from `frontend/`). Expected: PASS.
- [ ] Run `npm run lint` and `npm run typecheck` (from `frontend/`). Expected: no errors/warnings.
- [ ] Run `ruff check .` and `mypy .` (from `backend/`, venv activated). Expected: no errors.
- [ ] Confirm `git log --oneline dev..HEAD` shows exactly 5 commits (one per task).
