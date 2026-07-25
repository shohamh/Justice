# Help Modal Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the in-app help modal (`HelpModal.tsx`) role-aware (hide tabs a role can't act on, tailor wording for tabs everyone sees), cover systems that currently have no help text (Approvals, Hierarchy/Eligibility, Hakpaza, Import), turn the static flow diagrams into interactive/live widgets, and fix a real privacy gap found during the content audit (gimelim medical reason visible with no role check).

**Architecture:** Extract the permission predicates already living unexported in `searchRegistry.ts` (`isAdmin`, `canApprove`, `canPlan`, `authenticated`) into a shared `frontend/src/auth/permissions.ts` module. `HelpModal.tsx` moves from a hardcoded tab array to a registry of `{id, label, visible(user, gimelimEnabled)}` entries filtered before render, so an inaccessible tab never appears. Each new/changed tab component takes the `user` as a prop and branches copy/sections by role. New live widgets (eligibility checker, fairness "what if") only ever issue GETs against endpoints/data the viewer could already reach — no new write paths.

**Tech Stack:** React + TypeScript (frontend), FastAPI + SQLAlchemy + pytest (backend), Vitest + Testing Library (frontend tests).

## Global Constraints

- Hebrew UI copy, English code/identifiers (project-wide convention, see `CLAUDE.md`).
- `npm run lint` must stay at zero warnings; `npm run typecheck` must pass.
- Backend tests run via `pytest -q` (fast suite); this plan's new tests must pass in that run, not just `--slow`.
- No new backend endpoints for the eligibility/fairness widgets — reuse existing GETs (`fetchTree()`, `listTemplates()`, `getEffortBreakdown()`).
- Every new/changed help tab must keep working with `dir="rtl"` and existing dark-mode Tailwind classes (`dark:bg-...`, `dark:text-...`) already used throughout `HelpModal.tsx`.

---

## Task 1: Shared permission predicates

**Files:**
- Create: `frontend/src/auth/permissions.ts`
- Create: `frontend/src/auth/permissions.test.ts`
- Modify: `frontend/src/searchRegistry.ts:1-17`

**Interfaces:**
- Produces: `PermissionUser { role: "soldier"|"commander"|"duty_manager"|"admin"; is_commander: boolean; is_duty_manager: boolean }`, `isAdmin(user: PermissionUser | null): boolean`, `canApprove(user: PermissionUser | null): boolean`, `canPlan(user: PermissionUser | null): boolean`, `authenticated(user: PermissionUser | null): boolean`. All later tasks import these from `../auth/permissions` (or `./permissions` from within `auth/`).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/auth/permissions.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { authenticated, canApprove, canPlan, isAdmin, PermissionUser } from "./permissions";

const soldier: PermissionUser = { role: "soldier", is_commander: false, is_duty_manager: false };
const commander: PermissionUser = { role: "commander", is_commander: true, is_duty_manager: false };
const dutyManager: PermissionUser = { role: "duty_manager", is_commander: false, is_duty_manager: true };
const admin: PermissionUser = { role: "admin", is_commander: false, is_duty_manager: false };

describe("permission predicates", () => {
  it("authenticated is true for any non-null user, false for null", () => {
    expect(authenticated(soldier)).toBe(true);
    expect(authenticated(null)).toBe(false);
  });

  it("isAdmin is true only for admin role", () => {
    expect(isAdmin(admin)).toBe(true);
    expect(isAdmin(commander)).toBe(false);
    expect(isAdmin(null)).toBe(false);
  });

  it("canApprove is true for admin, commander, duty_manager, false for plain soldier", () => {
    expect(canApprove(admin)).toBe(true);
    expect(canApprove(commander)).toBe(true);
    expect(canApprove(dutyManager)).toBe(true);
    expect(canApprove(soldier)).toBe(false);
    expect(canApprove(null)).toBe(false);
  });

  it("canPlan is true for admin and duty_manager only", () => {
    expect(canPlan(admin)).toBe(true);
    expect(canPlan(dutyManager)).toBe(true);
    expect(canPlan(commander)).toBe(false);
    expect(canPlan(soldier)).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/auth/permissions.test.ts`
Expected: FAIL — `Cannot find module './permissions'`

- [ ] **Step 3: Write the implementation**

Create `frontend/src/auth/permissions.ts`:

```ts
export interface PermissionUser {
  role: "soldier" | "commander" | "duty_manager" | "admin";
  is_commander: boolean;
  is_duty_manager: boolean;
}

export function authenticated(user: PermissionUser | null): boolean {
  return user !== null;
}

export function isAdmin(user: PermissionUser | null): boolean {
  return user?.role === "admin";
}

export function canApprove(user: PermissionUser | null): boolean {
  return user?.role === "admin" || !!user?.is_commander || !!user?.is_duty_manager;
}

export function canPlan(user: PermissionUser | null): boolean {
  return user?.role === "admin" || !!user?.is_duty_manager;
}
```

Modify `frontend/src/searchRegistry.ts` — replace lines 1-17 (the `SearchUser` interface and the four local predicate functions) with:

```ts
import { authenticated, canApprove, canPlan, isAdmin, PermissionUser } from "./auth/permissions";

export type SearchUser = PermissionUser;
```

Leave the rest of the file (the `PageEntry`/`QuickActionEntry`/`HelpTopicEntry` interfaces and `getPageEntries`/`getHelpTopicEntries` functions) unchanged — they already reference `isAdmin`, `canApprove`, `canPlan`, `authenticated` by name, which now resolve to the imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/auth/permissions.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Confirm searchRegistry still compiles and its own tests pass**

Run: `cd frontend && npx vitest run src/searchRegistry.test.ts && npx tsc --noEmit`
Expected: PASS, no type errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/auth/permissions.ts frontend/src/auth/permissions.test.ts frontend/src/searchRegistry.ts
git commit -m "refactor: extract shared permission predicates from searchRegistry"
```

---

## Task 2: Fix dismissal-reason redaction (gimelim/reserve privacy gap)

**Context:** The audit found that `GET /api/calendar/shifts/{shift_id}` (`backend/app/routes/calendar.py:107-117`) returns each assignee's `dismissals[].reason` (which holds the gimelim medical reason) with **no redaction at all** — any authenticated user who can view a shift can read it. The sibling endpoint `GET /api/calendar/shifts?node_id=...` (`calendar.py:183-209`) does redact, but only for viewers without `HIERARCHY_READ` scope over the node — it does not special-case "the dismissed soldier viewing their own reason," so a plain soldier can't even see their own reason there. Fix both: only admin, a commander/duty-manager whose scope covers the assignee, or the assignee themself should see `reason`; everyone else gets `null`.

**Files:**
- Modify: `backend/app/routes/calendar.py`
- Modify: `backend/tests/integration/test_calendar_api.py`

**Interfaces:**
- Produces: `_visible_reason(user: Soldier, assignee_soldier_id: uuid.UUID, hierarchy_path_ids: list[str], roots: set[uuid.UUID], reason: str | None) -> str | None` in `calendar.py`, used by both `get_shift_detail` and `calendar_shifts`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/integration/test_calendar_api.py` (append at end of file):

```python
from datetime import date as _date

from app.db.models import DutyAssignment, DutyDismissal


def _create_dismissal(session, assignment_id, reason="בעיה רפואית"):
    d = DutyDismissal(
        duty_assignment_id=assignment_id,
        dismissed_from=_date(2026, 11, 1),
        dismissed_to=_date(2026, 11, 1),
        reason=reason,
    )
    session.add(d)
    session.commit()
    return d


def _setup_shift_with_dismissal(admin_session, client, admin):
    dept = create_node(admin_session, level="department", name="dep-reason")
    branch = create_node(admin_session, level="branch", name="br-reason", parent=dept)
    member = create_soldier(
        admin_session, personal_number="8200001", role="soldier", hierarchy_node_id=branch.id
    )
    admin_session.commit()
    dt = DutyType(name="שמירה-reason", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="מוצב-reason")
    admin_session.add_all([dt, loc])
    admin_session.commit()
    shift_resp = client.post(
        "/api/shifts",
        headers=auth_headers(admin),
        json={
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-11-01",
            "end_date": "2026-11-01",
            "required_count": 1,
        },
    )
    shift_id = shift_resp.json()["id"]
    assign_resp = client.post(
        "/api/assignments",
        headers=auth_headers(admin),
        json={
            "soldier_id": str(member.id),
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-11-01",
            "end_date": "2026-11-01",
            "duty_shift_id": shift_id,
        },
    )
    assignment_id = assign_resp.json()["id"]
    _create_dismissal(admin_session, assignment_id)
    return branch, member, shift_id


def test_shift_detail_hides_reason_from_outside_soldier(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="8200002", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)
    outsider = create_soldier(admin_session, personal_number="8200003", role="soldier")
    admin_session.commit()

    r = client.get(f"/api/calendar/shifts/{shift_id}", headers=auth_headers(outsider))
    assert r.status_code == 200, r.text
    assignee = next(a for a in r.json()["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["dismissals"][0]["reason"] is None


def test_shift_detail_shows_reason_to_affected_soldier(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="8200004", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)

    r = client.get(f"/api/calendar/shifts/{shift_id}", headers=auth_headers(member))
    assert r.status_code == 200, r.text
    assignee = next(a for a in r.json()["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["dismissals"][0]["reason"] == "בעיה רפואית"


def test_shift_detail_shows_reason_to_commander_in_scope(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="8200005", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)
    cmd = create_soldier(admin_session, personal_number="8200006", role="commander")
    branch.commander_id = cmd.id
    admin_session.commit()

    r = client.get(f"/api/calendar/shifts/{shift_id}", headers=auth_headers(cmd))
    assert r.status_code == 200, r.text
    assignee = next(a for a in r.json()["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["dismissals"][0]["reason"] == "בעיה רפואית"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_calendar_api.py -k reason -v`
Expected: FAIL — `test_shift_detail_hides_reason_from_outside_soldier` fails because `get_shift_detail` currently returns the reason unredacted to the outsider.

- [ ] **Step 3: Implement the redaction**

In `backend/app/routes/calendar.py`, add the shared helper after `_swap_counts_for_shifts` (after line 104) and before `get_shift_detail`:

```python
def _visible_reason(
    user: Soldier,
    assignee_soldier_id: uuid.UUID,
    hierarchy_path_ids: list[str],
    roots: set[uuid.UUID],
    reason: str | None,
) -> str | None:
    if reason is None:
        return None
    if user.role == "admin" or assignee_soldier_id == user.id:
        return reason
    path_uuids = {uuid.UUID(p) for p in hierarchy_path_ids}
    if roots & path_uuids:
        return reason
    return None


def _redact_shift_reasons(shift: CalendarShiftOut, user: Soldier, roots: set[uuid.UUID]) -> None:
    for assignee in shift.assignees:
        for d in assignee.dismissals:
            d.reason = _visible_reason(
                user, assignee.soldier_id, assignee.hierarchy_path_ids, roots, d.reason
            )
```

Replace `get_shift_detail` (lines 107-117) with:

```python
@router.get("/shifts/{shift_id}", response_model=CalendarShiftOut)
def get_shift_detail(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CalendarShiftOut:
    raw = get_single_shift(session, shift_id=shift_id)
    if raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    swap_count = _swap_counts_for_shifts(session, [shift_id]).get(shift_id, 0)
    shift = CalendarShiftOut(**raw, swap_request_count=swap_count)
    roots = scope_root_ids(session, user)
    _redact_shift_reasons(shift, user, roots)
    return shift
```

Replace the body of `calendar_shifts` (lines 183-209) — keep the signature, replace the `show_reason`/redaction block:

```python
@router.get("/shifts", response_model=CalendarShiftsResponse)
def calendar_shifts(
    node_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CalendarShiftsResponse:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    roots = scope_root_ids(session, user)
    raw = get_calendar_shifts(session, node_id=node_id, date_from=date_from, date_to=date_to)
    swap_counts = _swap_counts_for_shifts(session, [s["id"] for s in raw])
    shifts = []
    for s in raw:
        shift = CalendarShiftOut(**s, swap_request_count=swap_counts.get(s["id"], 0))
        _redact_shift_reasons(shift, user, roots)
        shifts.append(shift)
    return CalendarShiftsResponse(shifts=shifts)
```

Note: `is_commander`/`is_duty_manager`/`can`/`Action` imports on line 11 are no longer used by this file after this change if nothing else in `calendar.py` references them — check with a grep before removing:

Run: `cd backend && grep -n "is_commander\|is_duty_manager\|\bcan(\|Action\." app/routes/calendar.py`

If the only remaining uses are the ones just removed, update the import line (originally line 11) to:

```python
from app.auth.authz import authorize, scope_root_ids
```

(keep `authorize` since `unit_calendar` still calls it at line 131; drop `Action`, `can`, `is_commander`, `is_duty_manager` only if the grep shows no other usages).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_calendar_api.py -v`
Expected: PASS, all tests including the 3 new ones and the pre-existing 4.

- [ ] **Step 5: Run the full fast backend suite to check for regressions**

Run: `cd backend && pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/calendar.py backend/tests/integration/test_calendar_api.py
git commit -m "fix: redact dismissal reason unless viewer is admin, in-scope commander/DM, or the affected soldier"
```

---

## Task 3: HelpModal tab registry + capability-based visibility

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx:1-24,1012-1066`
- Create: `frontend/src/components/HelpModal.test.tsx`

**Interfaces:**
- Consumes: `PermissionUser`, `authenticated`, `canApprove`, `canPlan` from Task 1's `../auth/permissions`.
- Produces: `interface HelpTabDef { id: string; label: string; visible: (user: PermissionUser | null, gimelimEnabled: boolean) => boolean }`, `TAB_DEFS: HelpTabDef[]`, `buildTabs(user, gimelimEnabled): HelpTabDef[]` (replaces the existing `buildTabs(gimelimEnabled: boolean)` at lines 13-24). Later tasks (4, 6-9) each add one entry to `TAB_DEFS` and one `{activeTab === "id" && <XTab .../>}` line — this task's job is only to make the registry mechanism work with the 5 tabs that already exist.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/HelpModal.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import HelpModal from "./HelpModal";

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("../api/scoring", () => ({
  getEffortBreakdown: vi.fn(() => Promise.resolve({ quarters: [], effort_score: "0", A_i: "0", W_i: "0" })),
}));

function setUser(role: "soldier" | "commander" | "duty_manager" | "admin", overrides: Partial<{ is_commander: boolean; is_duty_manager: boolean }> = {}) {
  mockUseAuth.mockReturnValue({
    user: { id: "u1", role, is_commander: false, is_duty_manager: false, ...overrides },
  });
}

describe("HelpModal tab visibility", () => {
  it("hides Approvals and Import tabs from a plain soldier", () => {
    setUser("soldier");
    render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
    expect(screen.queryByText(/אישורים/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ייבוא/)).not.toBeInTheDocument();
    expect(screen.getByText(/החלפות/)).toBeInTheDocument();
  });

  it("shows Approvals but not Import to a commander", () => {
    setUser("commander", { is_commander: true });
    render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
    expect(screen.getByText(/אישורים/)).toBeInTheDocument();
    expect(screen.queryByText(/ייבוא/)).not.toBeInTheDocument();
  });

  it("shows Import to a duty manager", () => {
    setUser("duty_manager", { is_duty_manager: true });
    render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
    expect(screen.getByText(/ייבוא/)).toBeInTheDocument();
  });

  it("shows every tab to admin", () => {
    setUser("admin");
    render(<HelpModal onClose={() => {}} gimelimEnabled />);
    expect(screen.getByText(/אישורים/)).toBeInTheDocument();
    expect(screen.getByText(/ייבוא/)).toBeInTheDocument();
    expect(screen.getByText(/גימלים/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx`
Expected: FAIL — Approvals/Import tabs don't exist yet, `useAuth` isn't wired into `HelpModal` yet.

- [ ] **Step 3: Implement the registry**

In `frontend/src/components/HelpModal.tsx`, add the import (near the top, after existing imports):

```ts
import { authenticated, canApprove, canPlan, PermissionUser } from "../auth/permissions";
```

Replace lines 13-24 (`function buildTabs(gimelimEnabled: boolean) { ... }`) with:

```ts
interface HelpTabDef {
  id: string;
  label: string;
  visible: (user: PermissionUser | null, gimelimEnabled: boolean) => boolean;
}

const TAB_DEFS: HelpTabDef[] = [
  { id: "swaps", label: "🔄 החלפות", visible: (u) => authenticated(u) },
  { id: "algorithm", label: "⚙️ האלגוריתם", visible: (u) => authenticated(u) },
  { id: "fairness", label: "⚖️ הוגנות ושקיפות", visible: (u) => authenticated(u) },
  { id: "deep", label: "🔬 מאחורי הקלעים", visible: (u) => authenticated(u) },
  { id: "gimelim", label: "🏥 גימלים", visible: (u, gimelimEnabled) => authenticated(u) && gimelimEnabled },
];

function buildTabs(user: PermissionUser | null, gimelimEnabled: boolean): HelpTabDef[] {
  return TAB_DEFS.filter((t) => t.visible(user, gimelimEnabled));
}
```

(Tasks 6-9 will each insert one more object into `TAB_DEFS` and reference `canApprove`/`canPlan` — both already imported above so those tasks don't need to touch the import line again.)

Replace the component body (lines 1012-1066) with:

```tsx
export default function HelpModal({ onClose, gimelimEnabled = false, initialTab }: Props) {
  useModalBackClose(onClose);
  const { user } = useAuth();
  const TABS = buildTabs(user as PermissionUser | null, gimelimEnabled);
  const [activeTab, setActiveTab] = useState(() =>
    initialTab && TABS.some((t) => t.id === initialTab) ? initialTab : (TABS[0]?.id ?? "swaps")
  );

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 pt-5 pb-3 border-b dark:border-gray-600" dir="rtl">
          <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">מדריך המערכת</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
            aria-label="סגור"
          >
            ✕
          </button>
        </div>

        <div className="flex border-b dark:border-gray-600 px-2 pt-1 overflow-x-auto shrink-0" dir="rtl">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-3 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {activeTab === "swaps" && <SwapsTab />}
          {activeTab === "algorithm" && <AlgorithmTab />}
          {activeTab === "fairness" && <FairnessTab />}
          {activeTab === "deep" && <DeepDiveTab />}
          {activeTab === "gimelim" && <GimelimTab />}
        </div>
      </div>
    </div>
  );
}
```

Add the `useAuth` import at the top of the file if not already present (check first — `FairnessTab` already imports it at the current line 3):

Run: `grep -n "useAuth" frontend/src/components/HelpModal.tsx` — it's already imported at the top for `FairnessTab`'s use, so no new import line is needed; only the new top-level `const { user } = useAuth();` in `HelpModal` itself is added, as shown above.

- [ ] **Step 4: Run test to verify it passes for the existing tabs**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx`
Expected: the "hides Approvals/Import from soldier" and "shows every tab to admin" assertions for `אישורים`/`ייבוא` still FAIL (those tabs don't exist until Tasks 6/9) — this is expected at this point. The `החלפות`/`גימלים` assertions and the general rendering (no crash on `useAuth` call) should PASS. Confirm no crash and that `SwapsTab`/`FairnessTab`/etc. still render.

- [ ] **Step 5: Run typecheck and lint**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/components/HelpModal.test.tsx
git commit -m "refactor: turn HelpModal tabs into a capability-filtered registry"
```

---

## Task 4: Content fixes — gimelim privacy line + undocumented solver behavior

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` (`GimelimTab`, `AlgorithmTab`, `DeepDiveTab`)

- [ ] **Step 1: Correct the gimelim reason-visibility claim**

In `GimelimTab`, replace the bullet (originally):
```
<li>הסיבה הרפואית נשמרת לצפייה של מנהלי תורניות בלבד — לא מועברת לחיילים אחרים.</li>
```
with:
```tsx
<li>הסיבה הרפואית גלויה רק למי שרשאי: מנהל תורנויות או מפקד שבתחום אחריותם נמצא החייל, והחייל עצמו. חיילים אחרים לא רואים אותה.</li>
```

- [ ] **Step 2: Add undocumented-behavior callouts to `AlgorithmTab`**

In `AlgorithmTab`, inside the existing `{[{icon, title, desc}, ...].map(...)}` array (the "מה האלגוריתם לוקח בחשבון?" list), append four new entries before the closing `]`:

```tsx
{ icon: "🔁", title: "רענון מכסות תת-יחידה", desc: "אם רכיב לא נפתר במלואו, האלגוריתם מנסה שוב תוך הרפיה חד-פעמית של מכסות תת-היחידה (node quotas) — לפני שהוא עובר לסולם ההרפיה הרגיל (R/T)." },
{ icon: "🧩", title: "אסטרטגיות פתרון חלופיות", desc: "בנוסף לפירוק הרגיל לפי סבבי-עומס, קיימות אסטרטגיות פתרון חלופיות (למשל פתרון משולב על פני כמה משמרות בבת אחת) שהפותר עשוי להשתמש בהן במקרים מסוימים." },
{ icon: "⏹️", title: "עצירה מוקדמת", desc: "אם הפותר לא משפר את הפתרון במשך כ-15 שניות רצופות, הוא עוצר ומחזיר את הטוב ביותר שנמצא — במקום לנצל את כל זמן הריצה המוקצב." },
{ icon: "♻️", title: "גורל הרזרבה בגימלים", desc: "הגדרת מערכת קובעת מה קורה לרזרבה המקורית של חייל שעבר גימלים: נשארת משויכת אליו (\"keep\") או משוחררת (\"release\")." },
```

- [ ] **Step 3: Verify visually in a component test**

Add to `frontend/src/components/HelpModal.test.tsx`:

```tsx
it("shows corrected gimelim reason-visibility copy and undocumented-behavior callouts", () => {
  setUser("admin");
  render(<HelpModal onClose={() => {}} gimelimEnabled initialTab="gimelim" />);
  expect(screen.getByText(/מנהל תורנויות או מפקד שבתחום אחריותם/)).toBeInTheDocument();
});
```

- [ ] **Step 4: Run test**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx -t "corrected gimelim"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/components/HelpModal.test.tsx
git commit -m "docs: correct gimelim reason-visibility copy, document previously-undocumented solver behavior"
```

---

## Task 5: Swaps tab — clickable step-through

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` (`SwapsTab`, `FlowStep`)

**Interfaces:**
- Consumes: existing `FlowStep`/`Arrow` helpers.
- Produces: `FlowStep` gains an optional `detail?: string` and `onSelect?: () => void` prop; `SwapsTab` gains local `expandedStep: string | null` state.

- [ ] **Step 1: Extend `FlowStep` to be clickable and expandable**

Replace the `FlowStep` function (current lines 26-40) with:

```tsx
function FlowStep({
  icon, text, color = "indigo", detail, expanded, onToggle,
}: {
  icon: string; text: string; color?: string; detail?: string; expanded?: boolean; onToggle?: () => void;
}) {
  const colors: Record<string, string> = {
    indigo: "bg-indigo-50 dark:bg-indigo-950 border-indigo-200 dark:border-indigo-800 text-indigo-800 dark:text-indigo-200",
    green: "bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800 text-green-800 dark:text-green-200",
    red: "bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800 text-red-800 dark:text-red-200",
    amber: "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200",
    blue: "bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-200",
    gray: "bg-gray-50 dark:bg-gray-700 border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300",
  };
  const clickable = !!detail;
  return (
    <div>
      <div
        className={`border rounded-lg px-3 py-2 text-sm font-medium text-center ${colors[color] ?? colors.indigo} ${clickable ? "cursor-pointer hover:opacity-80" : ""}`}
        onClick={clickable ? onToggle : undefined}
        role={clickable ? "button" : undefined}
        tabIndex={clickable ? 0 : undefined}
      >
        {icon} {text} {clickable && (expanded ? "▲" : "▼")}
      </div>
      {clickable && expanded && (
        <div className="mt-1 text-xs bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg p-2 text-gray-600 dark:text-gray-300">
          {detail}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire the swap flow diagram in `SwapsTab` to use expandable steps**

In `SwapsTab`, add local state and pass `detail`/`expanded`/`onToggle` to each `FlowStep` in the flow diagram. Replace the flow-diagram block (inside the `<div className="bg-gray-50 ...">` wrapper) with:

```tsx
function SwapsTab() {
  const [expanded, setExpanded] = useState<string | null>(null);
  const toggle = (id: string) => setExpanded((cur) => (cur === id ? null : id));

  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">איך עובדות החלפות?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        מנגנון ההחלפות מאפשר לשני חיילים להחליף ביניהם תורנויות, בכפוף לאישור. לחצו על כל שלב כדי לראות מה קורה בפועל ולמה:
      </p>

      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600">
        <FlowStep
          icon="🙋" text="חייל מגיש בקשת החלפה" color="indigo"
          detail="החייל בוחר תורנות שלו ומבקש שמישהו אחר יבצע אותה במקומו. הבקשה יכולה להיות פתוחה (כל חייל יכול להציע עצמו) או ממוקדת לחייל ספציפי."
          expanded={expanded === "request"} onToggle={() => toggle("request")}
        />
        <Arrow split />
        <div className="grid grid-cols-2 gap-2">
          <FlowStep
            icon="📢" text="מתפרסם בלוח ההחלפות" color="blue"
            detail="כל חייל ביחידה יכול לראות את הבקשה ולהציע את עצמו כמחליף — שימושי כשלא ידוע מראש מי פנוי."
            expanded={expanded === "board"} onToggle={() => toggle("board")}
          />
          <FlowStep
            icon="📩" text="נשלחת הודעה לחייל המבוקש" color="blue"
            detail="רק החייל שצוין רואה את הבקשה ומחליט אם לאשר או לדחות אותה."
            expanded={expanded === "targeted"} onToggle={() => toggle("targeted")}
          />
        </div>
        <Arrow />
        <FlowStep
          icon="🤝" text="חייל מציע להחליף ושני הצדדים מאשרים" color="indigo"
          detail="שני החיילים חייבים להסכים לפני שהבקשה ממשיכה לשלב האישור הפיקודי."
          expanded={expanded === "agree"} onToggle={() => toggle("agree")}
        />
        <Arrow />
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <div className="text-center text-xs text-gray-400">נדרש אישור</div>
            <FlowStep
              icon="👮" text="מפקד אחד מהשרשרת מאשר" color="amber"
              detail="מספיק אישור אחד ממפקד רלוונטי לאחד הצדדים; אם אותו מפקד אחראי על שני הצדדים, האישור שלו מכסה את שניהם בבת אחת."
              expanded={expanded === "cmd-approve"} onToggle={() => toggle("cmd-approve")}
            />
            <FlowStep
              icon="🗂️" text="אחראי תורנויות מאשר" color="amber"
              detail="נדרש גם אישור נפרד של אחראי תורנויות — מפקד יכול לדחות גם אם אחראי התורנויות כבר אישר, וההפך."
              expanded={expanded === "dm-approve"} onToggle={() => toggle("dm-approve")}
            />
            <Arrow />
            <FlowStep icon="✅" text="ההחלפה בוצעה!" color="green" />
          </div>
          <div className="space-y-1">
            <div className="text-center text-xs text-gray-400">ללא אישור</div>
            <div className="h-16" />
            <Arrow />
            <FlowStep icon="✅" text="ההחלפה בוצעה!" color="green" />
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="bg-blue-50 dark:bg-blue-950 rounded-lg p-3 border border-blue-200 dark:border-blue-800">
          <p className="font-medium text-blue-800 dark:text-blue-200 mb-1">📌 בקשה פתוחה</p>
          <p className="text-blue-700 dark:text-blue-300">לא יודעים מי יחליף? כל חייל ביחידה יכול לראות את הבקשה ולהציע עצמו.</p>
        </div>
        <div className="bg-purple-50 dark:bg-purple-950 rounded-lg p-3 border border-purple-200 dark:border-purple-800">
          <p className="font-medium text-purple-800 dark:text-purple-200 mb-1">📌 בקשה ממוקדת</p>
          <p className="text-purple-700 dark:text-purple-300">יש מישהו ספציפי? ציינו אותו — הוא יקבל התראה ויאשר או ידחה.</p>
        </div>
        <div className="bg-amber-50 dark:bg-amber-950 rounded-lg p-3 border border-amber-200 dark:border-amber-800">
          <p className="font-medium text-amber-800 dark:text-amber-200 mb-1">⚠️ חשוב לדעת</p>
          <ul className="text-amber-700 dark:text-amber-300 space-y-1 list-disc list-inside">
            <li>החלפה אינה משפיעה על הניקוד — הניקוד נשאר על מי שסיפק את התורנות בפועל.</li>
            <li>המפקד רשאי לדחות גם אם שני הצדדים הסכימו.</li>
            <li>אם אותו מפקד או אותו אחראי תורנויות אחראים על שני הצדדים, אישור אחד שלו מספיק לשניהם.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write a test for the expand interaction**

Add to `frontend/src/components/HelpModal.test.tsx`:

```tsx
it("expands a swap step's detail on click and collapses on second click", async () => {
  const { default: userEvent } = await import("@testing-library/user-event");
  setUser("soldier");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="swaps" />);
  const step = screen.getByText(/חייל מגיש בקשת החלפה/);
  expect(screen.queryByText(/הבקשה יכולה להיות פתוחה/)).not.toBeInTheDocument();
  await userEvent.click(step);
  expect(screen.getByText(/הבקשה יכולה להיות פתוחה/)).toBeInTheDocument();
  await userEvent.click(step);
  expect(screen.queryByText(/הבקשה יכולה להיות פתוחה/)).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run test**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx -t "expands a swap step"`
Expected: PASS. (If `@testing-library/user-event` isn't already a project dependency, check `frontend/package.json` first — it's used elsewhere in the frontend test suite already; if genuinely absent, use `fireEvent.click(step)` from `@testing-library/react` instead, already imported at the top of the test file.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/components/HelpModal.test.tsx
git commit -m "feat: make swap flow diagram clickable with per-step detail"
```

---

## Task 6: New Approvals tab

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` (add `ApprovalsTab`, register in `TAB_DEFS` and render switch)
- Modify: `frontend/src/searchRegistry.ts` (`getHelpTopicEntries`)

**Interfaces:**
- Consumes: `canApprove` from `../auth/permissions` (already imported in `HelpModal.tsx` from Task 3).

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/HelpModal.test.tsx`:

```tsx
it("Approvals tab explains each approval type for a commander", () => {
  setUser("commander", { is_commander: true });
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="approvals" />);
  expect(screen.getByText(/בקשות החלפה/)).toBeInTheDocument();
  expect(screen.getByText(/בקשות פטור/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx -t "Approvals tab"`
Expected: FAIL — `approvals` tab doesn't exist.

- [ ] **Step 3: Implement `ApprovalsTab`**

Add before `export default function HelpModal` in `HelpModal.tsx`:

```tsx
function ApprovalsTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">תיבת האישורים</h3>
      <p className="text-gray-700 dark:text-gray-300">
        כל הבקשות שמחכות לאישור שלכם מרוכזות בעמוד <strong>אישורים</strong>, מחולקות לטאבים. אישור או דחייה כאן משפיעים מיידית על שיבוץ החייל — כדאי להבין את ההשפעה לפני שמחליטים:
      </p>
      <div className="space-y-2">
        {[
          { icon: "🔄", title: "בקשות החלפה", desc: "אישור מבצע את ההחלפה בפועל: מעביר את התורנות בין שני החיילים. דחייה משאירה את השיבוץ המקורי כפי שהיה — שני הצדדים מקבלים הודעה." },
          { icon: "🚫", title: "בקשות פטור", desc: "אישור מסיר את החייל משיבוץ עתידי לסוגי התורנות שבפטור. פטור רשמי גם מפחית את פוטנציאל היחידה (ראו טאב האלגוריתם) — כלומר אותו מספר תורנויות מתחלק בין פחות חיילים ביחידה." },
          { icon: "✏️", title: "עדכוני פרופיל", desc: "חייל ביקש לשנות פרט אישי (למשל טלפון או דרגה). אישור מעדכן את הרשומה מיד; דחייה משאירה את הערך הישן." },
          { icon: "🎓", title: "הצטרפויות/קליטה", desc: "חייל חדש שממתין לשיבוץ ליחידה. אישור קובע את היחידה שלו וממנו והלאה הוא נכנס לחישובי העומס וההוגנות." },
          { icon: "🔀", title: "העברות", desc: "העברת חייל בין תתי-יחידות. אישור מעביר את החייל וההיסטוריה שלו נשארת אך העומס העתידי נספר תחת היחידה החדשה." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="bg-amber-50 dark:bg-amber-950 rounded-lg p-3 border border-amber-200 dark:border-amber-800 text-xs text-amber-800 dark:text-amber-300">
        ⚠️ בקשות ממתינות זמן רב עלולות לחסום תכנון: תורנות שממתינה לאישור החלפה לא תיחשב "סופית" עד שהאישור יושלם.
      </div>
    </div>
  );
}
```

Add to `TAB_DEFS` (after the `"deep"` entry, before `"gimelim"` — order in the array is the display order in the tab bar):

```ts
{ id: "approvals", label: "✅ אישורים", visible: (u) => canApprove(u) },
```

Add to the render switch in `HelpModal`:

```tsx
{activeTab === "approvals" && <ApprovalsTab />}
```

- [ ] **Step 4: Add the matching search-registry entry**

In `frontend/src/searchRegistry.ts`, inside `getHelpTopicEntries(gimelimEnabled)`, add to the `topics` array (after the `"deep"` entry):

```ts
{ id: "approvals", labelKey: "search.help.approvals", keywords: ["אישורים", "approvals"], canAccess: canApprove },
```

The translation resource is `frontend/src/i18n/he.json`, which already has a nested `search.help` object (e.g. `"help": { "swaps": "🔄 החלפות", "algorithm": "⚙️ האלגוריתם", ... }` — emoji-prefixed, matching the tab labels verbatim, not plain text). Add a new key inside that same `search.help` object:

```json
"approvals": "✅ אישורים"
```
(i.e. add `"approvals": "✅ אישורים",` as a new line inside the existing `"help": { ... }` block in `frontend/src/i18n/he.json`, matching the emoji+label format of the existing entries there.)

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx src/searchRegistry.test.ts`
Expected: PASS

- [ ] **Step 6: Run typecheck and lint**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/components/HelpModal.test.tsx frontend/src/searchRegistry.ts frontend/src/i18n/he.json
git commit -m "feat: add Approvals help tab (commander/duty_manager/admin only)"
```

---

## Task 7: New Hierarchy/Eligibility tab with live widget

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` (add `HierarchyEligibilityTab`, register)
- Modify: `frontend/src/searchRegistry.ts`

**Interfaces:**
- Consumes: `fetchTree(): Promise<NodeDTO[]>` and `NodeDTO { id, name, path_ids: string[], children?: NodeDTO[] }` from `../api/hierarchy`; `listTemplates(): Promise<ShiftTemplate[]>` and `ShiftTemplate { id, name, eligible_node_ids: string[] | null }` from `../api/shiftTemplates`; `canPlan` from `../auth/permissions`.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/HelpModal.test.tsx` (add the two new mocks near the top of the file, alongside the existing `vi.mock` calls):

```tsx
vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn(() => Promise.resolve([
    { id: "n1", level: "unit", name: "פלוגה א", parent_id: null, commander_id: null, commander_name: null, path_ids: ["n1"], duty_managers: [], dm_manageable: false, can_edit: false, children: [
      { id: "n2", level: "team", name: "כיתה 1", parent_id: "n1", commander_id: null, commander_name: null, path_ids: ["n1", "n2"], duty_managers: [], dm_manageable: false, can_edit: false },
    ] },
  ])),
}));
vi.mock("../api/shiftTemplates", () => ({
  listTemplates: vi.fn(() => Promise.resolve([
    { id: "t1", name: "שמירה", duty_type_id: "d1", duty_location_id: "l1", recurrence_type: "daily", weekdays: [], duration_days: 1, start_time: "00:00", end_time: "23:59", required_count: 1, active: true, auto_roll: false, auto_roll_until: null, notes: null, eligible_node_ids: ["n1"] },
  ])),
}));
```

```tsx
it("eligibility checker shows a soldier in a matching subtree as eligible, for a duty_manager", async () => {
  setUser("duty_manager", { is_duty_manager: true });
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="hierarchy" />);
  const nodeSelect = await screen.findByLabelText("בחר צומת");
  const dutySelect = screen.getByLabelText("בחר סוג תורנות");
  fireEvent.change(nodeSelect, { target: { value: "n2" } });
  fireEvent.change(dutySelect, { target: { value: "t1" } });
  expect(await screen.findByText(/כשיר/)).toBeInTheDocument();
});

it("eligibility checker's duty-type dropdown is hidden for a plain soldier", async () => {
  setUser("soldier");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="hierarchy" />);
  await screen.findByLabelText("בחר צומת");
  expect(screen.queryByLabelText("בחר סוג תורנות")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx -t "eligibility checker"`
Expected: FAIL — `hierarchy` tab doesn't exist.

- [ ] **Step 3: Implement `HierarchyEligibilityTab`**

Add before `export default function HelpModal`:

```tsx
import { NodeDTO, fetchTree } from "../api/hierarchy";
import { ShiftTemplate, listTemplates } from "../api/shiftTemplates";

function flattenNodes(nodes: NodeDTO[]): NodeDTO[] {
  const out: NodeDTO[] = [];
  for (const n of nodes) {
    out.push(n);
    if (n.children) out.push(...flattenNodes(n.children));
  }
  return out;
}

function HierarchyEligibilityTab({ user }: { user: PermissionUser | null }) {
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [templates, setTemplates] = useState<ShiftTemplate[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string>("");
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");

  useEffect(() => {
    fetchTree().then((tree) => setNodes(flattenNodes(tree))).catch(() => setNodes([]));
  }, []);

  useEffect(() => {
    if (!canPlan(user)) return;
    listTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, [user]);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  const selectedTemplate = templates.find((t) => t.id === selectedTemplateId);
  const eligible = selectedNode && selectedTemplate
    ? !selectedTemplate.eligible_node_ids || selectedTemplate.eligible_node_ids.some((id) => selectedNode.path_ids.includes(id))
    : null;

  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">היררכיה וכשירות</h3>
      <p className="text-gray-700 dark:text-gray-300">
        כל משמרת יכולה להיות מוגבלת לתת-יחידה מסוימת. חייל כשיר אם אחד הצמתים הכשירים של המשמרת נמצא במסלול שלו מהשורש (<code>path_ids</code>) — כלומר הצומת שלו עצמו, או אחד מאבות-הקדמונים שלו.
      </p>

      <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 space-y-2">
        <p className="font-medium text-gray-800 dark:text-gray-200">🔎 בדיקת כשירות חיה</p>
        <label className="block text-xs text-gray-600 dark:text-gray-300">
          בחר צומת
          <select
            aria-label="בחר צומת"
            className="mt-1 w-full border rounded px-2 py-1 dark:bg-gray-800 dark:border-gray-600"
            value={selectedNodeId}
            onChange={(e) => setSelectedNodeId(e.target.value)}
          >
            <option value="">— בחר —</option>
            {nodes.map((n) => (
              <option key={n.id} value={n.id}>{n.name}</option>
            ))}
          </select>
        </label>
        {canPlan(user) && (
          <label className="block text-xs text-gray-600 dark:text-gray-300">
            בחר סוג תורנות
            <select
              aria-label="בחר סוג תורנות"
              className="mt-1 w-full border rounded px-2 py-1 dark:bg-gray-800 dark:border-gray-600"
              value={selectedTemplateId}
              onChange={(e) => setSelectedTemplateId(e.target.value)}
            >
              <option value="">— בחר —</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </label>
        )}
        {eligible !== null && (
          <p className={eligible ? "text-green-700 dark:text-green-300 font-medium" : "text-red-600 dark:text-red-400 font-medium"}>
            {eligible ? "✅ כשיר" : "❌ לא כשיר"}
          </p>
        )}
        {!canPlan(user) && (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            בדיקת כשירות מול סוגי תורנות ספציפיים זמינה למנהלי תורנויות ומפקדים בעלי הרשאת תכנון.
          </p>
        )}
      </div>
    </div>
  );
}
```

Add to `TAB_DEFS`:

```ts
{ id: "hierarchy", label: "🌳 היררכיה וכשירות", visible: (u) => authenticated(u) },
```

Add to the render switch:

```tsx
{activeTab === "hierarchy" && <HierarchyEligibilityTab user={user as PermissionUser | null} />}
```

- [ ] **Step 4: Add search-registry entry**

In `searchRegistry.ts`'s `getHelpTopicEntries`:

```ts
{ id: "hierarchy", labelKey: "search.help.hierarchy", keywords: ["היררכיה", "כשירות", "hierarchy"], canAccess: authenticated },
```

And the matching key inside the `"help": { ... }` object in `frontend/src/i18n/he.json`: `"hierarchy": "🌳 היררכיה וכשירות"`.

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx`
Expected: PASS (all tests in the file, including this task's two new ones)

- [ ] **Step 6: Typecheck and lint**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/components/HelpModal.test.tsx frontend/src/searchRegistry.ts frontend/src/i18n/he.json
git commit -m "feat: add live eligibility-checker help tab using real hierarchy/template data"
```

---

## Task 8: New Hakpaza tab

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx`
- Modify: `frontend/src/searchRegistry.ts`

- [ ] **Step 1: Write the failing test**

```tsx
it("Hakpaza tab is visible to commander, hidden from soldier", () => {
  setUser("commander", { is_commander: true });
  const { rerender } = render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="hakpaza" />);
  expect(screen.getByText(/הקפצה פיקודית/)).toBeInTheDocument();
  setUser("soldier");
  rerender(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
  expect(screen.queryByText(/הקפצה פיקודית/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx -t "Hakpaza tab"`
Expected: FAIL

- [ ] **Step 3: Implement `HakpazaTab`**

```tsx
function HakpazaTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-red-700 dark:text-red-400">📣 מה זו הקפצה פיקודית?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        הקפצה פיקודית מאפשרת למפקד למשוך חייל מתורנות קיימת ולהחליף אותו במועמד אחר — ללא תלות בבקשת החלפה הדדית. שימושי כשצריך מענה מיידי (למשל חייל שלא הגיע).
      </p>
      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-1">
        <FlowStep icon="🙋" text="מפקד בוחר תורנות וחייל שנמשך ממנה" color="red" />
        <Arrow />
        <FlowStep icon="📋" text="המערכת מציעה עד 8 מועמדים מדורגים" color="blue" />
        <Arrow />
        <FlowStep icon="✅" text="מפקד בוחר מועמד ומגיש בקשה" color="indigo" />
        <Arrow />
        <FlowStep icon="👮" text="נדרש אישור נוסף לפני שההקפצה נכנסת לתוקף" color="amber" />
        <Arrow />
        <FlowStep icon="📲" text="שני הצדדים מקבלים הודעה" color="green" />
      </div>
      <div className="space-y-2">
        {[
          { icon: "📏", title: "דירוג המועמדים", desc: "המועמדים מדורגים לפי קרבה היררכית לחייל שנמשך, עומס נוכחי (score_per_day), ומספר ימי התורנות שנותרו לו — כך שהעומס הנוסף מתחלק בצורה סבירה." },
          { icon: "⚖️", title: "מניעת שימוש חוזר באותו חייל", desc: "המערכת עוקבת אחרי הקפצות פיקודיות קודמות של כל חייל (עם דעיכה לאורך זמן) ומורידה את הדירוג שלו כמועמד ככל שהוקפץ יותר לאחרונה — כדי למנוע הישענות על אותם חיילים שוב ושוב." },
          { icon: "🔒", title: "צריך אישור", desc: "הקפצה לא נכנסת לתוקף מיידית — היא ממתינה לאישור נפרד (לרוב של גורם פיקודי נוסף) בדיוק כמו בקשת החלפה, ורק לאחריו התורנות בפועל מתחלפת." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

Add to `TAB_DEFS`:

```ts
{ id: "hakpaza", label: "📣 הקפצה פיקודית", visible: (u) => canApprove(u) },
```

Add to render switch:

```tsx
{activeTab === "hakpaza" && <HakpazaTab />}
```

- [ ] **Step 4: Add search-registry entry**

```ts
{ id: "hakpaza", labelKey: "search.help.hakpaza", keywords: ["הקפצה", "הקפצה פיקודית", "hakpaza"], canAccess: canApprove },
```
Matching key inside `"help": { ... }` in `frontend/src/i18n/he.json`: `"hakpaza": "📣 הקפצה פיקודית"`.

- [ ] **Step 5: Run tests, typecheck, lint**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx && npx tsc --noEmit && npm run lint`
Expected: PASS, no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/components/HelpModal.test.tsx frontend/src/searchRegistry.ts frontend/src/i18n/he.json
git commit -m "feat: add Hakpaza help tab (commander/duty_manager/admin only)"
```

---

## Task 9: New Import tab

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx`
- Modify: `frontend/src/searchRegistry.ts`

- [ ] **Step 1: Write the failing test**

```tsx
it("Import tab is visible to duty_manager, hidden from commander", () => {
  setUser("duty_manager", { is_duty_manager: true });
  const { rerender } = render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="import" />);
  expect(screen.getByText(/ייבוא מקובץ אקסל/)).toBeInTheDocument();
  setUser("commander", { is_commander: true });
  rerender(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
  expect(screen.queryByText(/ייבוא מקובץ אקסל/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx -t "Import tab"`
Expected: FAIL

- [ ] **Step 3: Implement `ImportTab`**

```tsx
function ImportTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">📥 ייבוא מקובץ אקסל</h3>
      <p className="text-gray-700 dark:text-gray-300">
        ייבוא מאפשר להזין או לעדכן חיילים, שיבוצים והגדרות ממקור אקסל חיצוני, בשלושה שלבים:
      </p>
      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-1">
        <FlowStep icon="📤" text="העלאת קובץ" color="indigo" />
        <Arrow />
        <FlowStep icon="🔍" text="סקירת שורות: חדש / עדכון / שגיאה / מחוץ לתחום / דילוג" color="blue" />
        <Arrow />
        <FlowStep icon="🛠️" text="מיפוי שמות ותיקוני שדות ידניים לפי הצורך" color="amber" />
        <Arrow />
        <FlowStep icon="✅" text="ביצוע (commit)" color="green" />
      </div>
      <div className="space-y-2">
        {[
          { icon: "🔄", title: "מה ההבדל בין 'חדש' ל'עדכון'?", desc: "שורה מזוהה לפי מספר אישי קיים במערכת: אם נמצא — זו 'עדכון' (שדות קיימים יידרסו בערכים מהקובץ); אם לא נמצא — 'חדש' (רשומה נוצרת מאפס)." },
          { icon: "⚠️", title: "שורות שגיאה ומחוץ לתחום", desc: "שורה עם שגיאה לא תיובא כלל עד לתיקון. שורה 'מחוץ לתחום' שייכת ליחידה שאין לכם הרשאה לנהל — היא מדולגת אוטומטית ולא תשפיע על היחידות שלכם." },
          { icon: "🗂️", title: "מיפוי שמות", desc: "אם שם סוג תורנות או שם צומת בקובץ לא תואם בדיוק למה שקיים במערכת, ניתן למפות אותו ידנית לפני הביצוע — כדי למנוע יצירת כפילויות בטעות." },
          { icon: "↩️", title: "לפני שמבצעים סופית", desc: "שום שינוי לא נכנס לתוקף עד לשלב הביצוע (commit) המפורש — סקירת השורות היא שלב תצוגה מקדימה בלבד וניתן לבטל בכל שלב לפני הביצוע." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

Add to `TAB_DEFS`:

```ts
{ id: "import", label: "📥 ייבוא", visible: (u) => canPlan(u) },
```

Add to render switch:

```tsx
{activeTab === "import" && <ImportTab />}
```

- [ ] **Step 4: Add search-registry entry**

```ts
{ id: "import", labelKey: "search.help.import", keywords: ["ייבוא", "אקסל", "import"], canAccess: canPlan },
```
Matching key inside `"help": { ... }` in `frontend/src/i18n/he.json`: `"import": "📥 ייבוא"`.

- [ ] **Step 5: Run tests, typecheck, lint**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx && npx tsc --noEmit && npm run lint`
Expected: PASS, no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/components/HelpModal.test.tsx frontend/src/searchRegistry.ts frontend/src/i18n/he.json
git commit -m "feat: add Import help tab (duty_manager/admin only)"
```

---

## Task 10: Fairness tab — live "what if" recompute

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` (`FairnessTab`)

**Interfaces:**
- Consumes: existing `EffortBreakdown { A_i: string; W_i: string; effort_score: string }` from `../api/scoring`, already fetched by `FairnessTab` via `getEffortBreakdown`.

- [ ] **Step 1: Write the failing test**

```tsx
it("fairness tab recomputes effort_score live when the what-if slider changes", async () => {
  const { getEffortBreakdown } = await import("../api/scoring");
  (getEffortBreakdown as ReturnType<typeof vi.fn>).mockResolvedValue({
    quarters: [], effort_score: "0.05", A_i: "0.20", W_i: "4.0",
  });
  setUser("soldier");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="fairness" />);
  const slider = await screen.findByLabelText("תורנויות נוספות היפותטיות");
  fireEvent.change(slider, { target: { value: "2" } });
  expect(await screen.findByText(/עומס לאחר התוספת/)).toBeInTheDocument();
});
```

(This requires `getEffortBreakdown` to already be mocked as a `vi.fn` in the test file's top-level `vi.mock("../api/scoring", ...)` — replace that existing mock block with `vi.mock("../api/scoring", () => ({ getEffortBreakdown: vi.fn() }));` so tests can call `.mockResolvedValue` per-test.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx -t "what-if slider"`
Expected: FAIL — no such control exists in `FairnessTab` yet.

- [ ] **Step 3: Add the what-if control to `FairnessTab`**

In `FairnessTab`, add local state:

```tsx
const [extraDuties, setExtraDuties] = useState(0);
```

Add this block directly after the existing "הנתונים שלי" (`🔢`) section's closing `</div>` (i.e., as a new sibling section before the "דוגמה מספרית" section), rendered only when `myBreakdown` is loaded:

```tsx
{myBreakdown && (
  <div className="bg-blue-50 dark:bg-blue-950 rounded-xl p-4 border border-blue-200 dark:border-blue-800 space-y-2">
    <p className="font-semibold text-blue-800 dark:text-blue-200">🎚️ מה אם אקבל עוד תורנויות?</p>
    <label className="block text-xs text-blue-700 dark:text-blue-300">
      תורנויות נוספות היפותטיות: {extraDuties}
      <input
        aria-label="תורנויות נוספות היפותטיות"
        type="range" min={0} max={10} value={extraDuties}
        onChange={(e) => setExtraDuties(Number(e.target.value))}
        className="w-full"
      />
    </label>
    {(() => {
      const A = parseFloat(myBreakdown.A_i);
      const W = parseFloat(myBreakdown.W_i);
      // Each hypothetical duty is treated as one full-weight duty this quarter (active_frac = 1),
      // contributing 1 unit to both the numerator's share and the denominator's weight — a
      // simplified, illustrative approximation of the real per-block calculation shown in the
      // Deep Dive tab, not the exact solver math.
      const projected = W + extraDuties > 0 ? (A + extraDuties) / (W + extraDuties) : 0;
      return (
        <p className="text-xs text-blue-700 dark:text-blue-300">
          עומס לאחר התוספת (הערכה): <span className="font-bold">{(projected * 100).toFixed(2)}%</span>
        </p>
      );
    })()}
  </div>
)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx -t "what-if slider"`
Expected: PASS

- [ ] **Step 5: Run the full HelpModal test file plus typecheck/lint**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx && npx tsc --noEmit && npm run lint`
Expected: PASS, no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/components/HelpModal.test.tsx
git commit -m "feat: add live what-if recompute to Fairness help tab"
```

---

## Task 11: Algorithm tab — draft/publish content + step-through worked example

**Note on scope:** the design spec suggested merging `AlgorithmModeHelpModal`'s content into the Algorithm tab and removing the standalone modal. On closer look, `AlgorithmModeHelpModal` is a small, focused inline "?" popup opened right next to the mode toggle on the shift-planning page (`AlgorithmInlinePanel.tsx:87-96`) — a different, tighter use case than the big Help Center. Ripping it out and forcing a detour through the full help modal would be a UX regression for that specific spot. This task instead **adds** the same draft/publish explanation as a new `canPlan`-gated section inside the Algorithm tab (for discoverability from the Help Center), while leaving `AlgorithmModeHelpModal` and `AlgorithmInlinePanel` untouched.

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` (`AlgorithmTab`, `DeepDiveTab`)

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/components/HelpModal.test.tsx`:

```tsx
it("Algorithm tab shows draft/publish mode section only for canPlan roles", () => {
  setUser("soldier");
  const { rerender } = render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="algorithm" />);
  expect(screen.queryByText(/מצב פרסום ישיר/)).not.toBeInTheDocument();
  setUser("duty_manager", { is_duty_manager: true });
  rerender(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="algorithm" />);
  expect(screen.getByText(/מצב פרסום ישיר/)).toBeInTheDocument();
});

it("Deep Dive worked example toggles between assignment A and B instead of showing both at once", () => {
  setUser("admin");
  render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="deep" />);
  expect(screen.getByText(/שיבוץ א׳/)).toBeInTheDocument();
  expect(screen.queryByText(/סה"כ = 520,000/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("שיבוץ ב׳ (גרוע יותר)"));
  expect(screen.getByText(/סה"כ = 520,000/)).toBeInTheDocument();
  expect(screen.queryByText(/סה"כ = 213,333/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx -t "Algorithm tab shows draft" -t "toggles between assignment"`
Expected: FAIL — section and toggle don't exist yet.

- [ ] **Step 3: Add the draft/publish section to `AlgorithmTab`**

`AlgorithmTab` currently takes no props; give it the `user` prop (and update its call site in the render switch to `<AlgorithmTab user={user as PermissionUser | null} />`). Add this block right after the existing "🔎 מה האלגוריתם לוקח בחשבון?" list and before the "📝 דוגמה מספרית" section:

```tsx
{canPlan(user) && (
  <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-3">
    <p className="font-semibold text-gray-800 dark:text-gray-200">🚦 מצבי הרצה (למי שמריץ את האלגוריתם)</p>
    <div className="bg-amber-50 dark:bg-amber-950 rounded-lg p-3 border border-amber-200 dark:border-amber-800">
      <p className="font-medium text-amber-800 dark:text-amber-200 mb-1">מצב טיוטה (ברירת מחדל)</p>
      <p className="text-amber-700 dark:text-amber-300 text-xs">
        תוצאות האלגוריתם נשמרות כטיוטה בלבד. החיילים לא רואים שינוי. אפשר לסקור את השיבוצים המוצעים, לדחות חלקם, ולפרסם רק אחרי אישור. מומלץ לשימוש רגיל.
      </p>
    </div>
    <div className="bg-green-50 dark:bg-green-950 rounded-lg p-3 border border-green-200 dark:border-green-800">
      <p className="font-medium text-green-800 dark:text-green-200 mb-1">מצב פרסום ישיר</p>
      <p className="text-green-700 dark:text-green-300 text-xs">
        תוצאות האלגוריתם מתפרסמות מיד ללא שלב ביניים. החיילים רואים את השיבוצים החדשים מיידית. השתמש רק כאשר אתה בטוח בתוצאות מראש.
      </p>
    </div>
  </div>
)}
```

Add the import for `canPlan`/`PermissionUser` if `AlgorithmTab` is defined above the point where `HelpModal.tsx` already imports them (Task 3 added the import at the top of the file, so no new import line is needed here — just reference `canPlan(user)`).

- [ ] **Step 4: Convert the worked-example (Assignment A / B) to a toggle in `DeepDiveTab`**

In `DeepDiveTab`, Section 8 ("🧮 דוגמה מספרית מלאה") currently renders both the "שיבוץ א׳" (green) and "שיבוץ ב׳" (red) blocks unconditionally, one after the other. Add local state to the component:

```tsx
const [shownAssignment, setShownAssignment] = useState<"a" | "b">("a");
```

Wrap the two existing blocks (the green "שיבוץ א׳..." `<div>` and the red "שיבוץ ב׳..." `<div>`) in a toggle:

```tsx
<div className="flex gap-2">
  <button
    type="button"
    onClick={() => setShownAssignment("a")}
    className={`text-xs px-2 py-1 rounded border ${shownAssignment === "a" ? "bg-green-600 text-white border-green-600" : "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300"}`}
  >
    שיבוץ א׳ (הפותר יבחר בזה)
  </button>
  <button
    type="button"
    onClick={() => setShownAssignment("b")}
    className={`text-xs px-2 py-1 rounded border ${shownAssignment === "b" ? "bg-red-600 text-white border-red-600" : "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300"}`}
  >
    שיבוץ ב׳ (גרוע יותר)
  </button>
</div>
{shownAssignment === "a" && (
  {/* existing green "שיבוץ א׳" div, unchanged, minus its own repeated heading paragraph since the toggle button now serves as the label */}
)}
{shownAssignment === "b" && (
  {/* existing red "שיבוץ ב׳" div, unchanged, minus its own repeated heading paragraph */}
)}
```

Concretely: keep both `<div className="bg-green-50 ...">...</div>` and `<div className="bg-red-50 ...">...</div>` blocks exactly as they are today, but delete their inner `<p className="font-semibold ...">שיבוץ א׳ (הפותר יבחר בזה): ...</p>` / `<p className="font-semibold ...">שיבוץ ב׳ (גרוע יותר): ...</p>` heading lines (now redundant with the toggle buttons above), and wrap each whole block in the matching `{shownAssignment === "a" && ( ... )}` / `{shownAssignment === "b" && ( ... )}` condition.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/HelpModal.test.tsx`
Expected: PASS (full file, all tasks' tests)

- [ ] **Step 6: Typecheck and lint**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/components/HelpModal.test.tsx
git commit -m "feat: add draft/publish section to Algorithm tab, make Deep Dive worked example a toggle"
```

---

## Final check

- [ ] Run the full frontend test suite and the full fast backend suite once more to confirm nothing regressed:

Run: `cd frontend && npm test && cd ../backend && pytest -q`
Expected: PASS
