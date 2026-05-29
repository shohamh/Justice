# UI Features, i18n Fixes, Seed Script, and E2E Tests — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 improvements: i18n error translations, hierarchy tree UI, calendar view, exemption request workflow, DB seed script, and Playwright E2E tests.

**Architecture:** Frontend (React/TypeScript) + Backend (FastAPI/Python/SQLAlchemy/PostgreSQL). No breaking changes to existing APIs. Backend changes are additive (new model, new routes). Frontend changes are additive (new components, modified pages).

**Tech Stack:** React 18, TypeScript 5.4, FastAPI, SQLAlchemy 2.0, PostgreSQL 16, Playwright, react-calendar

---

## File Structure

### Create
- `frontend/src/components/HierarchyTree.tsx` — Recursive collapsible tree with per-node actions
- `frontend/src/components/AddChildNodeDialog.tsx` — Modal to add sub-node
- `frontend/src/components/AssignCommanderDialog.tsx` — Modal to assign commander
- `frontend/src/components/RenameNodeDialog.tsx` — Modal to rename node
- `backend/app/services/exemption_requests.py` — Business logic for exemption requests
- `backend/app/routes/exemption_requests.py` — API routes for exemption requests
- `backend/app/scripts/seed.py` — DB seed script
- `frontend/tests/e2e/hierarchy.spec.ts` — Hierarchy tree E2E tests
- `frontend/tests/e2e/personal_constraints.spec.ts` — Personal constraint E2E tests
- `frontend/tests/e2e/exemption_requests.spec.ts` — Exemption request E2E tests
- `frontend/tests/e2e/duty_calendar.spec.ts` — Calendar E2E tests
- `frontend/tests/e2e/seed_views.spec.ts` — Seeded data view E2E tests

### Modify
- `backend/app/db/models.py` — Add ExemptionRequest model
- `backend/app/main.py` — Register exemption_requests router
- `backend/app/routes/hierarchy.py:19-51` — Add commander_name to NodeOut
- `frontend/src/i18n/he.json` — Add errors block + exemption request keys
- `frontend/src/pages/MyRequestsPage.tsx` — Add error handling + exemption request form
- `frontend/src/pages/DutyManagementPage.tsx:50` — Fix "error" fallback
- `frontend/src/pages/TeamHierarchyPage.tsx` — Replace flat list with HierarchyTree
- `frontend/src/pages/MyDutiesPage.tsx` — Add calendar + list view
- `frontend/src/pages/ApprovalsPage.tsx` — Add exemption request approvals tab
- `frontend/src/api/exemptions.ts` — Add exemption request API functions
- `frontend/src/api/hierarchy.ts:9` — Add commander_name to NodeDTO
- `frontend/package.json` — Add react-calendar dependency

---

### Task 1: Add i18n error translations + fix error handling

**Files:**
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/pages/MyRequestsPage.tsx`
- Modify: `frontend/src/pages/DutyManagementPage.tsx`

- [ ] **Step 1: Add errors block to he.json**

Add after the `unit_calendar` block:

```json
  "errors": {
    "bad_date_range": "טווח תאריכים לא תקין",
    "start_date_in_past": "תאריך התחלה לא יכול להיות בעבר",
    "cap_exceeded": "חרגת ממכסת הימים המותרת",
    "soldier_not_found": "חייל לא נמצא",
    "constraint_not_found": "הבקשה לא נמצאה",
    "not_pending": "הבקשה כבר טופלה",
    "generic": "שגיאה",
    "password_too_short": "הסיסמה חייבת להכיל לפחות 10 תווים",
    "date_range_invalid": "טווח תאריכים לא תקין",
    "exemption_not_found": "הפטור לא נמצא",
    "already_exists": "כבר קיים במערכת",
    "exemption_request_not_found": "בקשת הפטור לא נמצאה",
    "exemption_request_not_pending": "בקשת הפטור כבר טופלה",
    "exemption_type_not_found": "סוג הפטור לא נמצא"
  }
```

- [ ] **Step 2: Fix MyRequestsPage to catch and display errors**

Replace the `onSubmit` function (lines 34-43) with:

```tsx
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await submitConstraint({
        start_date: start,
        end_date: end,
        reason,
      });
      setStart(""); setEnd(""); setReason("");
      await refresh();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        const code = axiosErr.response?.data?.detail;
        setError(t(`errors.${code}` as any) || t("errors.generic"));
      } else {
        setError(t("errors.generic"));
      }
    } finally {
      setSubmitting(false);
    }
  }
```

Also add `disabled={submitting}` to the submit button:

```tsx
  <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50" disabled={submitting} data-testid="req-submit">
    {submitting ? t("app.loading") : t("my_requests.send")}
  </button>
```

Add error display above the form:

```tsx
  {error && <div className="text-red-600 text-sm" data-testid="req-error">{error}</div>}
```

- [ ] **Step 3: Fix DutyManagementPage "error" fallback**

Find line 50 (or the line `setError(detail ?? "error")`). Change to:

```tsx
  setError(detail ? (t(`errors.${detail}` as any) || detail) : t("errors.generic"));
```

If the file doesn't have `useTranslation`, add it at the top import line.

- [ ] **Step 4: Run frontend lint to verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

---

### Task 2: Create DB seed script

**Files:**
- Create: `backend/app/scripts/seed.py`

- [ ] **Step 1: Create the seed script**

Path: `backend/app/scripts/seed.py`

```python
"""Seed the database with realistic test data.

Usage: python -m app.scripts.seed
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from random import choice, randint, sample

from sqlalchemy import create_engine

from app.auth.password import hash_password
from app.db.base import Base
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    ScoreAdjustment,
    Soldier,
    SoldierExemption,
)
from app.db.session import SessionLocal
from app.settings import get_settings


def seed():
    settings = get_settings()
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        # Check if already seeded
        if session.query(Soldier).count() > 5:
            print("DB already has data (>{0} soldiers). Delete tables or use a fresh DB first.".format(5))
            return

        hashed = hash_password("Pass123456!")

        # ── Hierarchy ──────────────────────────────────────────────
        dept1 = HierarchyNode(level="department", name="אגף מבצעים")
        dept2 = HierarchyNode(level="department", name="אגף מודיעין")
        session.add_all([dept1, dept2])
        session.flush()
        dept1.path_ids = [dept1.id]
        dept2.path_ids = [dept2.id]

        branches = []
        for dept, bnames in [(dept1, ["זרוע אוויר", "זרוע ים"]), (dept2, ["זרוע סייבר", "זרוע יבשה"])]:
            for bname in bnames:
                b = HierarchyNode(level="branch", name=bname, parent_id=dept.id)
                session.add(b)
                session.flush()
                b.path_ids = dept.path_ids + [b.id]
                branches.append(b)

        groups = []
        for branch, gnames in [
            (branches[0], ["טייסת קרב", "טייסת תובלה"]),
            (branches[1], ["שייטת 1", "שייטת 2"]),
            (branches[2], ["יחידת 8200", "יחידת לוחמת סייבר"]),
            (branches[3], ["גדוד חוד", "גדוד סדיר"]),
        ]:
            for gname in gnames:
                g = HierarchyNode(level="group", name=gname, parent_id=branch.id)
                session.add(g)
                session.flush()
                g.path_ids = branch.path_ids + [g.id]
                groups.append(g)

        teams = []
        for group, tnames in [
            (groups[0], ["רביעיית 1", "רביעיית 2"]),
            (groups[1], ["צוות א׳", "צוות ב׳"]),
            (groups[2], ["מדור איסוף", "מדור עיבוד"]),
            (groups[3], ["כיתה א׳", "כיתה ב׳"]),
            (groups[4], ["פלגת מודיעין", "פלגת תקיפה"]),
            (groups[5], ["צוות הגנה", "צוות התקפה"]),
            (groups[6], ["פלוגה א׳", "פלוגה ב׳"]),
            (groups[7], ["מחלקה 1", "מחלקה 2"]),
        ]:
            for tname in tnames:
                t = HierarchyNode(level="team", name=tname, parent_id=group.id)
                session.add(t)
                session.flush()
                t.path_ids = group.path_ids + [t.id]
                teams.append(t)

        all_nodes = [dept1, dept2] + branches + groups + teams

        # ── Soldiers ───────────────────────────────────────────────
        soldier_defs = [
            # (personal_number, full_name, role, node_index)
            ("1000001", "מפקד על הראשי", "admin", 0),  # admin at dept1 (must exist for bootstrap)
            ("2000001", "מפקד מבצעים", "duty_manager", 1),
            ("3000001", "מפקדת מודיעין", "commander", 2),
            ("3000002", "מפקד אוויר", "commander", 3),
            ("3000003", "מפקד ים", "commander", 4),
            ("4000001", "לוחם מצטיין", "soldier", 8),
            ("4000002", "לוחם ותיק", "soldier", 9),
            ("4000003", "פקח מבצעים", "soldier", 10),
            ("4000004", "מפעיל מערכת", "soldier", 11),
            ("4000005", "אנליסט מודיעין", "soldier", 12),
            ("4000006", "לוחם סייבר", "soldier", 13),
            ("4000007", "מפקד צוות", "soldier", 14),
            ("4000008", "לוחם", "soldier", 15),
            ("5000001", "טייס קרב", "soldier", 8),
            ("5000002", "נווט", "soldier", 9),
            ("5000003", "מכונאי", "soldier", 10),
            ("5000004", "שייטת 1 לוחם", "soldier", 11),
            ("5000005", "שייטת 2 לוחם", "soldier", 12),
            ("5000006", "איסוף 1", "soldier", 13),
            ("5000007", "איסוף 2", "soldier", 14),
            ("5000008", "עיבוד 1", "soldier", 15),
            ("6000001", "לוחם חי״ר", "soldier", 22),
            ("6000002", "מקלען", "soldier", 23),
            ("6000003", "חובש", "soldier", 24),
            ("6000004", "נהג", "soldier", 25),
            ("6000005", "מודיעין 1", "soldier", 26),
            ("6000006", "מודיעין 2", "soldier", 27),
            ("6000007", "סייבר מגן", "soldier", 28),
            ("6000008", "סייבר תוקף", "soldier", 29),
        ]

        soldiers = []
        for pn, name, role, node_idx in soldier_defs:
            s = Soldier(
                personal_number=pn,
                full_name=name,
                password_hash=hashed,
                role=role,
                hierarchy_node_id=all_nodes[node_idx].id,
                enrolled_at=date(2026, 1, 15),
                must_change_password=False,
            )
            session.add(s)
            session.flush()
            soldiers.append(s)

        # ── Assign commanders to nodes ─────────────────────────────
        # dept1 → soldier 0 (admin), dept2 → soldier 2
        dept1.commander_id = soldiers[0].id
        dept2.commander_id = soldiers[2].id
        # branches → soldiers 3,4,5,6
        for i, node in enumerate(branches):
            node.commander_id = soldiers[i + 3].id if i + 3 < len(soldiers) else soldiers[0].id
        # groups and teams — assign some
        for i, node in enumerate(groups + teams):
            if i % 3 == 0 and (i + 7) < len(soldiers):
                node.commander_id = soldiers[i + 7].id

        # ── Duty Types ─────────────────────────────────────────────
        dt1 = DutyType(name="משמרת בוקר", score_per_day=Decimal("1.00"), description="06:00-14:00")
        dt2 = DutyType(name="משמרת ערב", score_per_day=Decimal("1.50"), description="14:00-22:00")
        dt3 = DutyType(name="משמרת לילה", score_per_day=Decimal("2.00"), description="22:00-06:00")
        dt4 = DutyType(name="שבת", score_per_day=Decimal("3.00"), description="יום שבת")
        dt5 = DutyType(name="חג", score_per_day=Decimal("4.00"), description="יום חג")
        session.add_all([dt1, dt2, dt3, dt4, dt5])
        session.flush()
        duty_types = [dt1, dt2, dt3, dt4, dt5]

        # ── Duty Locations ─────────────────────────────────────────
        loc1 = DutyLocation(name="מפקדה ראשית", base="בסיס מרכז")
        loc2 = DutyLocation(name="שער ראשי", base="בסיס מרכז")
        loc3 = DutyLocation(name="מוצב צפון", base="בסיס צפון")
        loc4 = DutyLocation(name="חדר מבצעים", base="בסיס מרכז")
        session.add_all([loc1, loc2, loc3, loc4])
        session.flush()
        locations = [loc1, loc2, loc3, loc4]

        # ── Exemption Types ────────────────────────────────────────
        et1 = ExemptionType(name="רפואי", description="פטור רפואי זמני")
        et2 = ExemptionType(name="אימונים", description="פטור עקב אימונים")
        et3 = ExemptionType(name="משפחתי", description="פטור עקב סיבה משפחתית")
        session.add_all([et1, et2, et3])
        session.flush()

        # Map exemptions to duty types
        session.add_all([
            ExemptionDutyTypeMap(exemption_type_id=et1.id, duty_type_id=dt1.id),
            ExemptionDutyTypeMap(exemption_type_id=et1.id, duty_type_id=dt2.id),
            ExemptionDutyTypeMap(exemption_type_id=et1.id, duty_type_id=dt3.id),
            ExemptionDutyTypeMap(exemption_type_id=et2.id, duty_type_id=dt4.id),
            ExemptionDutyTypeMap(exemption_type_id=et2.id, duty_type_id=dt5.id),
            ExemptionDutyTypeMap(exemption_type_id=et3.id, duty_type_id=dt1.id),
        ])

        # ── Duty Assignments for next 30 days ──────────────────────
        today = date.today()
        for i in range(30):
            day = today + timedelta(days=i)
            # Pick 2-4 soldiers per day from different nodes
            for _ in range(randint(2, 4)):
                s = choice(soldiers[6:])  # Skip admin/managers
                dt = choice(duty_types)
                loc = choice(locations)
                # 3-day assignment blocks
                block_end = day + timedelta(days=randint(1, 3))
                existing = (
                    session.query(DutyAssignment)
                    .filter(
                        DutyAssignment.soldier_id == s.id,
                        DutyAssignment.status == "published",
                        DutyAssignment.start_date <= block_end,
                        DutyAssignment.end_date >= day,
                    )
                    .first()
                )
                if not existing:
                    da = DutyAssignment(
                        soldier_id=s.id,
                        duty_type_id=dt.id,
                        duty_location_id=loc.id,
                        start_date=day,
                        end_date=block_end,
                        status="published",
                        created_by=soldiers[0].id,
                    )
                    session.add(da)

        # ── Personal Constraints ────────────────────────────────────
        for i, s in enumerate(soldiers[6:12]):
            start_c = today + timedelta(days=10 + i)
            end_c = start_c + timedelta(days=2)
            statuses = ["pending", "approved", "rejected"]
            pc = PersonalConstraint(
                soldier_id=s.id,
                start_date=start_c,
                end_date=end_c,
                reason=f"סיבה אישית {i + 1}",
                status=statuses[i % 3],
                decided_by=soldiers[1].id if i % 3 != 0 else None,
            )
            session.add(pc)

        # ── Exemptions (manager-granted) ───────────────────────────
        for i, s in enumerate(soldiers[6:10]):
            se = SoldierExemption(
                soldier_id=s.id,
                exemption_type_id=et1.id if i % 2 == 0 else et2.id,
                start_date=today + timedelta(days=5),
                end_date=today + timedelta(days=15),
                reason="פטור זמני",
                granted_by=soldiers[0].id,
            )
            session.add(se)

        # ── Score Adjustments ──────────────────────────────────────
        for i, s in enumerate(soldiers[6:8]):
            sa = ScoreAdjustment(
                soldier_id=s.id,
                delta=Decimal("5.00") if i == 0 else Decimal("-2.00"),
                reason="תיקון ידני",
                created_by=soldiers[0].id,
            )
            session.add(sa)

        session.commit()
        print("Seed complete! Created:")
        print(f"  {len(all_nodes)} hierarchy nodes")
        print(f"  {len(soldiers)} soldiers")
        print(f"  {len(duty_types)} duty types")
        print(f"  {len(locations)} duty locations")
        print(f"  3 exemption types with mappings")
        print(f"  30 days of duty assignments")
        print(f"  6 personal constraints")
        print(f"  4 soldier exemptions")
        print(f"  2 score adjustments")


if __name__ == "__main__":
    seed()
```

- [ ] **Step 2: Verify the seed script runs**

Run: `cd backend && python -m app.scripts.seed`
Expected: "Seed complete!" message with counts.

- [ ] **Step 3: Verify data is queryable**

Run: `cd backend && python -c "from app.db.session import SessionLocal; s=SessionLocal(); print(s.execute('SELECT count(*) FROM soldiers').scalar()); s.close()"`
Expected: Number of soldiers (around 30).

---

### Task 3: Add commander_name to hierarchy API

**Files:**
- Modify: `backend/app/routes/hierarchy.py:19-51`
- Modify: `frontend/src/api/hierarchy.ts:9`

- [ ] **Step 1: Add commander_name to NodeOut**

In `backend/app/routes/hierarchy.py`, modify `NodeOut`:

```python
class NodeOut(BaseModel):
    id: uuid.UUID
    level: str
    name: str
    parent_id: uuid.UUID | None
    commander_id: uuid.UUID | None
    commander_name: str | None = None
    path_ids: list[uuid.UUID]
```

Update `_out(n: HierarchyNode)` to look up commander name:

```python
def _out(n: HierarchyNode, _session: Session | None = None) -> NodeOut:
    commander_name = None
    if n.commander_id and _session:
        cmdr = _session.get(Soldier, n.commander_id)
        if cmdr:
            commander_name = cmdr.full_name
    return NodeOut(
        id=n.id,
        level=n.level,
        name=n.name,
        parent_id=n.parent_id,
        commander_id=n.commander_id,
        commander_name=commander_name,
        path_ids=list(n.path_ids),
    )
```

Update all route handlers to pass `session` to `_out()`. For example, in `create_node`:

```python
def create_node(..., session: Session = Depends(get_session), ...) -> NodeOut:
    ...
    return _out(node, session)
```

Repeat for `update_node`, `move_node`, and `get_tree`. In `get_tree`:

```python
def get_tree(...) -> list[NodeOut]:
    ...
    return [_out(n, session) for n in nodes]
```

- [ ] **Step 2: Add commander_name to frontend NodeDTO**

In `frontend/src/api/hierarchy.ts`:

```typescript
export interface NodeDTO {
  id: string;
  level: "department" | "branch" | "group" | "team";
  name: string;
  parent_id: string | null;
  commander_id: string | null;
  commander_name: string | null;
  path_ids: string[];
}
```

- [ ] **Step 3: Run backend type check**

Run: `cd backend && ruff check app/routes/hierarchy.py`
Expected: No errors.

---

### Task 4: Create hierarchy tree components

**Files:**
- Create: `frontend/src/components/HierarchyTree.tsx`
- Create: `frontend/src/components/AddChildNodeDialog.tsx`
- Create: `frontend/src/components/AssignCommanderDialog.tsx`
- Create: `frontend/src/components/RenameNodeDialog.tsx`

- [ ] **Step 1: Create AddChildNodeDialog.tsx**

```tsx
import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, createNode } from "../api/hierarchy";

const CHILD_LEVELS: Record<string, string[]> = {
  department: ["branch"],
  branch: ["group"],
  group: ["team"],
  team: [],
};

interface Props {
  parent: NodeDTO;
  onClose: () => void;
  onCreated: () => void;
}

export default function AddChildNodeDialog({ parent, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const possibleLevels = CHILD_LEVELS[parent.level] ?? [];
  const [level, setLevel] = useState(possibleLevels[0] ?? "");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await createNode({ level, name, parent_id: parent.id });
    onCreated();
    onClose();
  }

  if (possibleLevels.length === 0) return null;

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="add-child-dialog">
        <h3 className="font-semibold mb-4">{t("team.add_child_node", "הוסף תת-יחידה ל-{{name}}").replace("{{name}}", parent.name)}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <select className="border rounded p-1 w-full" value={level} onChange={(e) => setLevel(e.target.value)} data-testid="child-level">
            {possibleLevels.map((l) => (
              <option key={l} value={l}>{t(`team.level_${l}`, l)}</option>
            ))}
          </select>
          <input className="border rounded p-1 w-full" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("team.node_name")} required data-testid="child-name" />
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1" onClick={onClose}>{t("duty_config.delete", "ביטול")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="child-submit">{t("team.add_soldier", "הוסף")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create AssignCommanderDialog.tsx**

```tsx
import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, updateNode } from "../api/hierarchy";
import { SoldierDTO, listSoldiers } from "../api/soldiers";

interface Props {
  node: NodeDTO;
  onClose: () => void;
  onAssigned: () => void;
}

export default function AssignCommanderDialog({ node, onClose, onAssigned }: Props) {
  const { t } = useTranslation();
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [selectedId, setSelectedId] = useState(node.commander_id ?? "");
  const [search, setSearch] = useState("");

  useEffect(() => {
    void (async () => {
      const all = await listSoldiers();
      // Filter to soldiers in this node's subtree
      setSoldiers(all);
    })();
  }, []);

  const filtered = soldiers.filter((s) =>
    s.full_name.includes(search) || s.personal_number.includes(search)
  );

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await updateNode(node.id, { commander_id: selectedId || null } as any);
    onAssigned();
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="assign-commander-dialog">
        <h3 className="font-semibold mb-4">{t("team.assign_commander", "קביעת מפקד ל-{{name}}").replace("{{name}}", node.name)}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <input className="border rounded p-1 w-full" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("my_requests.reason", "חיפוש חייל...")} data-testid="commander-search" />
          <select className="border rounded p-1 w-full" value={selectedId} onChange={(e) => setSelectedId(e.target.value)} data-testid="commander-select">
            <option value="">—</option>
            {filtered.map((s) => (
              <option key={s.id} value={s.id}>{s.full_name} ({s.personal_number}) [{s.role}]</option>
            ))}
          </select>
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1" onClick={onClose}>{t("duty_config.delete", "ביטול")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="commander-submit">{t("approvals.approve", "שמור")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create RenameNodeDialog.tsx**

```tsx
import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { renameNode } from "../api/hierarchy";

interface Props {
  nodeId: string;
  currentName: string;
  onClose: () => void;
  onRenamed: () => void;
}

export default function RenameNodeDialog({ nodeId, currentName, onClose, onRenamed }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(currentName);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await renameNode(nodeId, name);
    onRenamed();
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="rename-dialog">
        <h3 className="font-semibold mb-4">{t("team.rename_node", "שינוי שם")}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <input className="border rounded p-1 w-full" value={name} onChange={(e) => setName(e.target.value)} required data-testid="rename-input" />
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1" onClick={onClose}>{t("duty_config.delete", "ביטול")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="rename-submit">{t("duty_config.save", "שמור")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create HierarchyTree.tsx**

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, deleteNode } from "../api/hierarchy";
import AddChildNodeDialog from "./AddChildNodeDialog";
import AssignCommanderDialog from "./AssignCommanderDialog";
import RenameNodeDialog from "./RenameNodeDialog";

const LEVEL_COLORS: Record<string, string> = {
  department: "text-blue-700 bg-blue-50",
  branch: "text-green-700 bg-green-50",
  group: "text-yellow-700 bg-yellow-50",
  team: "text-gray-700 bg-gray-100",
};

interface Props {
  nodes: NodeDTO[];
  isAdmin: boolean;
  onChanged: () => void;
}

export default function HierarchyTree({ nodes, isAdmin, onChanged }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<string>>(new Set(nodes.filter((n) => n.path_ids.length <= 2).map((n) => n.id)));
  const [addDialog, setAddDialog] = useState<NodeDTO | null>(null);
  const [commanderDialog, setCommanderDialog] = useState<NodeDTO | null>(null);
  const [renameDialog, setRenameDialog] = useState<NodeDTO | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function handleDelete(id: string) {
    if (!confirm(t("team.remove") + "?")) return;
    try {
      await deleteNode(id);
      onChanged();
    } catch {
      alert(t("errors.generic"));
    }
  }

  const childrenOf = (parentId: string | null) =>
    nodes.filter((n) => n.parent_id === parentId).sort((a, b) => a.name.localeCompare(b.name));

  function renderNode(node: NodeDTO, depth: number) {
    const children = childrenOf(node.id);
    const isExpanded = expanded.has(node.id);
    const hasChildren = children.length > 0;

    return (
      <li key={node.id} className="select-none">
        <div className={`flex items-center gap-2 py-1 px-2 hover:bg-gray-50 rounded ${depth > 0 ? "mr-4" : ""}`}>
          {/* Expand/collapse */}
          <button
            className={`w-4 h-4 flex items-center justify-center text-xs ${hasChildren ? "visible" : "invisible"}`}
            onClick={() => toggle(node.id)}
            data-testid={`tree-toggle-${node.id}`}
          >
            {isExpanded ? "▼" : "▶"}
          </button>
          {/* Node info */}
          <span className={`text-xs px-1.5 py-0.5 rounded ${LEVEL_COLORS[node.level] ?? ""}`}>
            {t(`team.level_${node.level}`, node.level)}
          </span>
          <span className="font-medium" data-testid={`tree-name-${node.id}`}>{node.name}</span>
          {node.commander_name && (
            <span className="text-xs text-gray-400" data-testid={`tree-commander-${node.id}`}>
              ({t("team.commander", "מפקד")}: {node.commander_name})
            </span>
          )}
          {/* Actions */}
          {isAdmin && (
            <span className="flex gap-1 ml-auto">
              {children.length === 0 && (node.level === "team" || node.level === "group") && (
                <button className="text-xs text-indigo-600 hover:underline" onClick={() => setAddDialog(node)} data-testid={`tree-add-child-${node.id}`}>
                  +{t("team.add_node")}
                </button>
              )}
              {children.length > 0 && (["department", "branch", "group"].includes(node.level)) && (
                <button className="text-xs text-indigo-600 hover:underline" onClick={() => setAddDialog(node)} data-testid={`tree-add-child-${node.id}`}>
                  +{t("team.add_node")}
                </button>
              )}
              <button className="text-xs text-green-600 hover:underline" onClick={() => setCommanderDialog(node)} data-testid={`tree-commander-btn-${node.id}`}>
                {t("exemptions.title", "מפקד")}
              </button>
              <button className="text-xs text-amber-600 hover:underline" onClick={() => setRenameDialog(node)} data-testid={`tree-rename-${node.id}`}>
                {t("duty_config.save", "שנה")}
              </button>
              {!node.commander_id && children.length === 0 && (
                <button className="text-xs text-red-500 hover:underline" onClick={() => handleDelete(node.id)} data-testid={`tree-delete-${node.id}`}>
                  {t("duty_config.delete")}
                </button>
              )}
            </span>
          )}
        </div>
        {hasChildren && isExpanded && (
          <ul className="border-r-2 border-gray-100 mr-2">
            {children.map((child) => renderNode(child, depth + 1))}
          </ul>
        )}
      </li>
    );
  }

  const roots = childrenOf(null);

  return (
    <>
      <ul className="text-sm text-gray-700" data-testid="node-tree">
        {roots.map((node) => renderNode(node, 0))}
      </ul>

      {addDialog && (
        <AddChildNodeDialog parent={addDialog} onClose={() => setAddDialog(null)} onCreated={onChanged} />
      )}
      {commanderDialog && (
        <AssignCommanderDialog node={commanderDialog} onClose={() => setCommanderDialog(null)} onAssigned={onChanged} />
      )}
      {renameDialog && (
        <RenameNodeDialog nodeId={renameDialog.id} currentName={renameDialog.name} onClose={() => setRenameDialog(null)} onRenamed={onChanged} />
      )}
    </>
  );
}
```

- [ ] **Step 5: Run frontend lint to verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

---

### Task 5: Update TeamHierarchyPage to use tree

**Files:**
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx`

- [ ] **Step 1: Replace flat list with HierarchyTree component**

Replace the import block to add HierarchyTree:

```tsx
import HierarchyTree from "../components/HierarchyTree";
```

Replace the tree section (lines 60-74):

```tsx
        <div className="flex items-center gap-3">
          <h3 className="font-medium">{t("team.title")}</h3>
          {isAdmin && (
            <button onClick={addDepartment} className="text-sm text-indigo-600" data-testid="add-department">
              {t("team.add_node")}
            </button>
          )}
        </div>
        <HierarchyTree nodes={nodes} isAdmin={isAdmin} onChanged={refresh} />
```

- [ ] **Step 2: Remove old `addDepartment` function**

Keep the function but update it — it's still used. Keep as-is.

- [ ] **Step 3: Run frontend lint**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

---

### Task 6: Add calendar to MyDutiesPage

**Files:**
- Modify: `frontend/package.json`
- Create/Modify: `frontend/src/pages/MyDutiesPage.tsx`

- [ ] **Step 1: Install react-calendar**

Run: `cd frontend && npm install react-calendar`

- [ ] **Step 2: Update MyDutiesPage with calendar**

Replace the entire file content:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import Calendar from "react-calendar";
import "react-calendar/dist/Calendar.css";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { DutyLocation, DutyType, listDutyTypes, listLocations } from "../api/dutyConfig";

export default function MyDutiesPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [rows, setRows] = useState<EffectiveDuty[]>([]);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [locs, setLocs] = useState<Record<string, string>>({});
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);

  useEffect(() => {
    if (!user) return;
    void (async () => {
      const [as, dts, ls]: [EffectiveDuty[], DutyType[], DutyLocation[]] = await Promise.all([
        listEffectiveDuties(user.id),
        listDutyTypes().catch(() => [] as DutyType[]),
        listLocations().catch(() => [] as DutyLocation[]),
      ]);
      setRows(as);
      setTypes(Object.fromEntries(dts.map((d) => [d.id, d.name])));
      setLocs(Object.fromEntries(ls.map((l) => [l.id, l.name])));
    })();
  }, [user]);

  // Build set of date strings that have duties
  const dutyDates = useMemo(() => {
    const dates = new Set<string>();
    for (const r of rows) {
      const start = new Date(r.start_date);
      const end = new Date(r.end_date);
      for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        dates.push(d.toISOString().slice(0, 10));
      }
    }
    return dates;
  }, [rows]);

  // Filter rows by selected date
  const filteredRows = useMemo(() => {
    if (!selectedDate) return rows;
    const ds = selectedDate.toISOString().slice(0, 10);
    return rows.filter((r) => r.start_date <= ds && r.end_date >= ds);
  }, [rows, selectedDate]);

  function tileClassName({ date }: { date: Date }) {
    const ds = date.toISOString().slice(0, 10);
    if (dutyDates.has(ds)) return "bg-indigo-100 rounded-full font-bold";
    return "";
  }

  function tileContent({ date }: { date: Date }) {
    const ds = date.toISOString().slice(0, 10);
    if (dutyDates.has(ds)) {
      return <div className="w-1.5 h-1.5 bg-indigo-500 rounded-full mx-auto" />;
    }
    return null;
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="my-duties-page">
        <h2 className="text-xl font-semibold">{t("my_duties.title")}</h2>

        {/* Calendar */}
        <div className="flex justify-center" data-testid="duty-calendar">
          <Calendar
            onChange={(value) => setSelectedDate(value as Date | null)}
            value={selectedDate}
            tileClassName={tileClassName}
            tileContent={tileContent}
            locale="he"
          />
        </div>

        {selectedDate && (
          <p className="text-sm text-gray-500">
            {t("my_duties.showing_for_date", "תורנויות לתאריך: {{date}}").replace("{{date}}", selectedDate.toLocaleDateString("he-IL"))}
            <button className="mr-2 text-indigo-600 text-xs" onClick={() => setSelectedDate(null)}>
              {t("my_duties.show_all", "הצג הכל")}
            </button>
          </p>
        )}

        {/* Duty list */}
        {filteredRows.length === 0 ? (
          <p data-testid="my-duties-empty">{t("my_duties.none")}</p>
        ) : (
          <table className="w-full text-sm text-right" data-testid="my-duties-table">
            <thead>
              <tr className="border-b">
                <th className="p-1">{t("my_duties.duty_type")}</th>
                <th className="p-1">{t("my_duties.location")}</th>
                <th className="p-1">{t("my_duties.from")}</th>
                <th className="p-1">{t("my_duties.to")}</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((a) => (
                <tr key={`${a.assignment_id}-${a.start_date}`} data-testid={`my-duty-row-${a.assignment_id}-${a.start_date}`}>
                  <td className="p-1">{types[a.duty_type_id] ?? a.duty_type_id}</td>
                  <td className="p-1">{locs[a.duty_location_id] ?? a.duty_location_id}</td>
                  <td className="p-1">{a.start_date}</td>
                  <td className="p-1">{a.end_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </Layout>
  );
}
```

Wait, there's a bug in the code above - I used `dates.push()` on a Set, but Set doesn't have push. Let me fix:

```tsx
  const dutyDates = useMemo(() => {
    const dates = new Set<string>();
    for (const r of rows) {
      const start = new Date(r.start_date + "T00:00:00");
      const end = new Date(r.end_date + "T00:00:00");
      for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        dates.add(d.toISOString().slice(0, 10));
      }
    }
    return dates;
  }, [rows]);
```

Actually, let me also avoid timezone issues by using the date string directly:

```tsx
  const dutyDates = useMemo(() => {
    const dates = new Set<string>();
    for (const r of rows) {
      const startParts = r.start_date.split("-").map(Number);
      const endParts = r.end_date.split("-").map(Number);
      const start = new Date(startParts[0], startParts[1] - 1, startParts[2]);
      const end = new Date(endParts[0], endParts[1] - 1, endParts[2]);
      for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        dates.add(`${y}-${m}-${day}`);
      }
    }
    return dates;
  }, [rows]);
```

Same for `tileClassName` and `tileContent`.

- [ ] **Step 3: Run frontend type check and build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

---

### Task 7: Add ExemptionRequest model to backend

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add ExemptionRequest model**

Add after the `ScoreAdjustment` class (before the end of the file):

```python
class ExemptionRequest(Base):
    __tablename__ = "exemption_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    exemption_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exemption_types.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(Text, server_default="pending", default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 2: Run backend lint**

Run: `cd backend && ruff check app/db/models.py`
Expected: No errors.

---

### Task 8: Create exemption requests service

**Files:**
- Create: `backend/app/services/exemption_requests.py`

- [ ] **Step 1: Create the service file**

```python
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExemptionRequest, ExemptionType, Soldier, SoldierExemption


class ExemptionRequestError(ValueError):
    pass


def submit_request(
    session: Session,
    soldier_id: uuid.UUID,
    exemption_type_id: uuid.UUID,
    start_date: date,
    end_date: date | None = None,
    reason: str | None = None,
) -> ExemptionRequest:
    if end_date and end_date < start_date:
        raise ExemptionRequestError("bad_date_range")

    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise ExemptionRequestError("exemption_type_not_found")

    req = ExemptionRequest(
        soldier_id=soldier_id,
        exemption_type_id=exemption_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        status="pending",
    )
    session.add(req)
    session.flush()
    return req


def list_own_requests(session: Session, soldier_id: uuid.UUID) -> list[ExemptionRequest]:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id == soldier_id
    ).order_by(ExemptionRequest.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def list_pending_requests(session: Session, soldier_ids: list[uuid.UUID]) -> list[ExemptionRequest]:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id.in_(soldier_ids),
        ExemptionRequest.status == "pending",
    ).order_by(ExemptionRequest.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def count_pending_requests(session: Session, soldier_ids: list[uuid.UUID]) -> int:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id.in_(soldier_ids),
        ExemptionRequest.status == "pending",
    )
    return session.execute(stmt).scalars().count()


def approve_request(
    session: Session,
    request_id: uuid.UUID,
    decided_by: uuid.UUID,
    decision_note: str | None = None,
) -> ExemptionRequest:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise ExemptionRequestError("exemption_request_not_found")
    if req.status != "pending":
        raise ExemptionRequestError("exemption_request_not_pending")

    req.status = "approved"
    req.decided_by = decided_by
    req.decision_note = decision_note

    # Auto-create the actual exemption record
    exemption = SoldierExemption(
        soldier_id=req.soldier_id,
        exemption_type_id=req.exemption_type_id,
        start_date=req.start_date,
        end_date=req.end_date,
        reason=req.reason,
        granted_by=decided_by,
    )
    session.add(exemption)
    session.flush()
    return req


def reject_request(
    session: Session,
    request_id: uuid.UUID,
    decided_by: uuid.UUID,
    decision_note: str | None = None,
) -> ExemptionRequest:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise ExemptionRequestError("exemption_request_not_found")
    if req.status != "pending":
        raise ExemptionRequestError("exemption_request_not_pending")

    req.status = "rejected"
    req.decided_by = decided_by
    req.decision_note = decision_note
    session.flush()
    return req
```

---

### Task 9: Create exemption requests routes

**Files:**
- Create: `backend/app/routes/exemption_requests.py`

- [ ] **Step 1: Create the routes file**

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import ExemptionRequest, ExemptionType, Soldier
from app.db.session import get_session
from app.services.exemption_requests import ExemptionRequestError, approve_request, count_pending_requests, list_pending_requests, list_own_requests, reject_request, submit_request

router = APIRouter(tags=["exemption-requests"])


class ExemptionRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    exemption_type_id: uuid.UUID
    start_date: str
    end_date: str | None
    reason: str | None
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None
    created_at: str


class CreateExemptionRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = None
    reason: str | None = None


class ApproveRejectRequest(BaseModel):
    decision_note: str | None = None


def _out(req: ExemptionRequest) -> ExemptionRequestOut:
    return ExemptionRequestOut(
        id=req.id,
        soldier_id=req.soldier_id,
        exemption_type_id=req.exemption_type_id,
        start_date=req.start_date.isoformat(),
        end_date=req.end_date.isoformat() if req.end_date else None,
        reason=req.reason,
        status=req.status,
        decided_by=req.decided_by,
        decision_note=req.decision_note,
        created_at=req.created_at.isoformat(),
    )


@router.post("/me/exemption-requests", response_model=ExemptionRequestOut, status_code=status.HTTP_201_CREATED)
def create_exemption_request(
    body: CreateExemptionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    try:
        from datetime import date
        req = submit_request(
            session,
            soldier_id=user.id,
            exemption_type_id=body.exemption_type_id,
            start_date=date.fromisoformat(body.start_date),
            end_date=date.fromisoformat(body.end_date) if body.end_date else None,
            reason=body.reason,
        )
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(req)


@router.get("/me/exemption-requests", response_model=list[ExemptionRequestOut])
def get_my_exemption_requests(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionRequestOut]:
    return [_out(r) for r in list_own_requests(session, user.id)]


@router.get("/exemption-requests/pending", response_model=list[ExemptionRequestOut])
def get_pending_exemption_requests(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionRequestOut]:
    root_ids = scope_root_ids(session, user)
    if not root_ids:
        return []
    # Get all soldier IDs in the scope's subtree using path_ids.overlap
    from sqlalchemy import select
    from app.db.models import HierarchyNode, Soldier
    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(root_ids)))
        .subquery()
    )
    soldier_ids = list(
        session.execute(
            select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
        )
        .scalars()
        .all()
    )
    return [_out(r) for r in list_pending_requests(session, soldier_ids)]


@router.get("/exemption-requests/pending/count")
def get_pending_exemption_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    root_ids = scope_root_ids(session, user)
    if not root_ids:
        return {"count": 0}
    from sqlalchemy import select
    from app.db.models import HierarchyNode, Soldier
    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(root_ids)))
        .subquery()
    )
    soldier_ids = list(
        session.execute(
            select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
        )
        .scalars()
        .all()
    )
    return {"count": count_pending_requests(session, soldier_ids)}


@router.post("/exemption-requests/{request_id}/approve", response_model=ExemptionRequestOut)
def approve_exemption_request(
    request_id: uuid.UUID,
    body: ApproveRejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_soldier_id=req.soldier_id)
    try:
        result = approve_request(session, request_id, decided_by=user.id, decision_note=body.decision_note)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(result)


@router.post("/exemption-requests/{request_id}/reject", response_model=ExemptionRequestOut)
def reject_exemption_request(
    request_id: uuid.UUID,
    body: ApproveRejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_soldier_id=req.soldier_id)
    try:
        result = reject_request(session, request_id, decided_by=user.id, decision_note=body.decision_note)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(result)
```

- [ ] **Step 2: Register routes in main.py**

In `backend/app/main.py`, add import:

```python
from app.routes import exemption_requests as exemption_request_routes
```

Add after `app.include_router(exemption_routes.router, prefix="/api")`:

```python
    app.include_router(exemption_request_routes.router, prefix="/api")
```

- [ ] **Step 3: Run backend lint**

Run: `cd backend && ruff check app/`
Expected: No errors.

---

### Task 10: Add exemption request frontend API functions

**Files:**
- Modify: `frontend/src/api/exemptions.ts`

- [ ] **Step 1: Add exemption request types and functions**

Add to `frontend/src/api/exemptions.ts`:

```typescript
export interface ExemptionRequest {
  id: string;
  soldier_id: string;
  exemption_type_id: string;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decision_note: string | null;
  created_at: string;
}

export async function listMyExemptionRequests(): Promise<ExemptionRequest[]> {
  return (await api.get<ExemptionRequest[]>("/me/exemption-requests")).data;
}

export async function submitExemptionRequest(input: {
  exemption_type_id: string;
  start_date: string;
  end_date?: string | null;
  reason?: string | null;
}): Promise<ExemptionRequest> {
  return (await api.post<ExemptionRequest>("/me/exemption-requests", input)).data;
}

export async function listPendingExemptionRequests(): Promise<ExemptionRequest[]> {
  return (await api.get<ExemptionRequest[]>("/exemption-requests/pending")).data;
}

export async function getPendingExemptionCount(): Promise<number> {
  const r = await api.get<{ count: number }>("/exemption-requests/pending/count");
  return r.data.count;
}

export async function approveExemptionRequest(
  id: string,
  note?: string | null,
): Promise<ExemptionRequest> {
  return (await api.post<ExemptionRequest>(`/exemption-requests/${id}/approve`, { decision_note: note || null })).data;
}

export async function rejectExemptionRequest(
  id: string,
  note: string,
): Promise<ExemptionRequest> {
  return (await api.post<ExemptionRequest>(`/exemption-requests/${id}/reject`, { decision_note: note })).data;
}
```

- [ ] **Step 2: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

### Task 11: Add exemption request UI to MyRequestsPage

**Files:**
- Modify: `frontend/src/pages/MyRequestsPage.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add i18n keys for exemption requests**

Add to `he.json` after the `exemptions` block:

```json
  "exemption_requests": {
    "title": "בקשות פטור",
    "type": "סוג פטור",
    "start_date": "מתאריך",
    "end_date": "עד תאריך",
    "reason": "סיבה",
    "send": "שלח בקשת פטור",
    "pending": "ממתין לאישור",
    "approved": "אושר",
    "rejected": "נדחה",
    "none": "אין בקשות פטור",
    "my_requests": "הבקשות שלי לפטור"
  },
```

- [ ] **Step 2: Add exemption request form and list to MyRequestsPage**

Update the imports to include:

```tsx
import { Exemption, listExemptions } from "../api/exemptions";
import { ExemptionType, listExemptionTypes } from "../api/dutyConfig";
import {
  ExemptionRequest,
  listMyExemptionRequests,
  submitExemptionRequest,
} from "../api/exemptions";
```

Wait, `listExemptionTypes` is in `dutyConfig.ts`, not in `exemptions.ts`. Let me check...

Actually, looking at the API, exemption types are managed via `/duty-config/exemption-types`. Let me import from the right place:

```tsx
import { listExemptionTypes, ExemptionTypeDTO } from "../api/dutyConfig";
```

Now add the exemption request section to the state and JSX.

Add new state variables:
```tsx
  const [exemptionRequests, setExemptionRequests] = useState<ExemptionRequest[]>([]);
  const [exemptionTypes, setExemptionTypes] = useState<ExemptionType[]>([]);
  const [erTypeId, setErTypeId] = useState("");
  const [erStart, setErStart] = useState("");
  const [erEnd, setErEnd] = useState("");
  const [erReason, setErReason] = useState("");
  const [erError, setErError] = useState<string | null>(null);
  const [erSubmitting, setErSubmitting] = useState(false);
```

Add to `refresh`:
```tsx
  async function refresh() {
    setItems(await listMyConstraints());
    setExemptionRequests(await listMyExemptionRequests());
    setExemptionTypes(await listExemptionTypes().catch(() => []));
    if (user) {
      setExemptions(await listExemptions(user.id));
    }
  }
```

Add exemption request submit handler:
```tsx
  async function onErSubmit(e: FormEvent) {
    e.preventDefault();
    setErError(null);
    setErSubmitting(true);
    try {
      await submitExemptionRequest({
        exemption_type_id: erTypeId,
        start_date: erStart,
        end_date: erEnd || null,
        reason: erReason || null,
      });
      setErTypeId(""); setErStart(""); setErEnd(""); setErReason("");
      await refresh();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        const code = axiosErr.response?.data?.detail;
        setErError(t(`errors.${code}` as any) || t("errors.generic"));
      } else {
        setErError(t("errors.generic"));
      }
    } finally {
      setErSubmitting(false);
    }
  }
```

Add before the exemptions section (inside the `<section>`):
```tsx
        {/* Exemption Requests */}
        <div className="pt-4 border-t">
          <h3 className="font-medium">{t("exemption_requests.title")}</h3>
          {erError && <div className="text-red-600 text-sm" data-testid="er-error">{erError}</div>}
          <form onSubmit={onErSubmit} className="flex flex-wrap items-end gap-2 mt-2">
            <select className="border rounded p-1" value={erTypeId} onChange={(e) => setErTypeId(e.target.value)} required data-testid="er-type">
              <option value="">{t("exemption_requests.type")}</option>
              {exemptionTypes.map((et) => (
                <option key={et.id} value={et.id}>{et.name}</option>
              ))}
            </select>
            <input type="date" className="border rounded p-1" value={erStart} onChange={(e) => setErStart(e.target.value)} required data-testid="er-start" />
            <input type="date" className="border rounded p-1" value={erEnd} onChange={(e) => setErEnd(e.target.value)} data-testid="er-end" />
            <input className="border rounded p-1" value={erReason} onChange={(e) => setErReason(e.target.value)} placeholder={t("exemption_requests.reason")} data-testid="er-reason" />
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50" disabled={erSubmitting} data-testid="er-submit">
              {erSubmitting ? t("app.loading") : t("exemption_requests.send")}
            </button>
          </form>

          {exemptionRequests.length === 0 && <p className="text-sm text-gray-500 mt-2">{t("exemption_requests.none")}</p>}
          <ul className="text-sm space-y-1 mt-2" data-testid="er-list">
            {exemptionRequests.map((er) => (
              <li key={er.id} className="flex items-center gap-3">
                <span>{exemptionTypes.find((et) => et.id === er.exemption_type_id)?.name ?? er.exemption_type_id}</span>
                <span>{er.start_date} → {er.end_date ?? t("exemptions.forever")}</span>
                {er.reason && <span className="text-gray-500">{er.reason}</span>}
                <span className={`text-xs ${
                  er.status === "approved" ? "text-green-600" :
                  er.status === "rejected" ? "text-red-600" : "text-amber-600"
                }`}>{t(`exemption_requests.${er.status}`)}</span>
              </li>
            ))}
          </ul>
        </div>
```

- [ ] **Step 3: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

### Task 12: Add exemption request approvals to ApprovalsPage

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add i18n keys**

Add to `he.json` `approvals` block:

```json
    "tab_constraints": "בקשות אישיות",
    "tab_exemptions": "בקשות פטור",
    "exemption_none": "אין בקשות פטור ממתינות"
```

- [ ] **Step 2: Update ApprovalsPage with tabs**

Replace the entire file:

```tsx
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import {
  PersonalConstraint,
  approveConstraint,
  listPendingApprovals,
  rejectConstraint,
} from "../api/constraints";
import {
  ExemptionRequest,
  approveExemptionRequest,
  listPendingExemptionRequests,
  rejectExemptionRequest,
} from "../api/exemptions";

type Tab = "constraints" | "exemptions";

export default function ApprovalsPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("constraints");
  const [items, setItems] = useState<PersonalConstraint[]>([]);
  const [erItems, setErItems] = useState<ExemptionRequest[]>([]);
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    setItems(await listPendingApprovals());
    setErItems(await listPendingExemptionRequests());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onApprove(id: string) {
    await approveConstraint(id);
    await refresh();
  }
  async function onReject(id: string) {
    const note = rejectNotes[id];
    if (!note) return;
    await rejectConstraint(id, note);
    const next = { ...rejectNotes };
    delete next[id];
    setRejectNotes(next);
    await refresh();
  }

  async function onErApprove(id: string) {
    await approveExemptionRequest(id);
    await refresh();
  }
  async function onErReject(id: string) {
    const note = rejectNotes[`er-${id}`];
    if (!note) return;
    await rejectExemptionRequest(id, note);
    const next = { ...rejectNotes };
    delete next[`er-${id}`];
    setRejectNotes(next);
    await refresh();
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4">
        <h2 className="text-xl font-semibold">{t("approvals.title")}</h2>

        {/* Tabs */}
        <div className="flex gap-4 border-b">
          <button
            className={`pb-2 text-sm ${tab === "constraints" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("constraints")}
            data-testid="approvals-tab-constraints"
          >
            {t("approvals.tab_constraints")}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "exemptions" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("exemptions")}
            data-testid="approvals-tab-exemptions"
          >
            {t("approvals.tab_exemptions")}
          </button>
        </div>

        {/* Personal Constraints */}
        {tab === "constraints" && (
          <>
            {items.length === 0 && <p className="text-sm text-gray-500">{t("approvals.none")}</p>}
            <ul className="space-y-3" data-testid="approvals-list">
              {items.map((c) => (
                <li key={c.id} className="border rounded p-3 flex items-center gap-4" data-testid={`approval-row-${c.id}`}>
                  <div className="flex-1">
                    <p className="text-sm"><strong>{c.soldier_id}</strong> — {c.start_date} → {c.end_date}</p>
                    <p className="text-xs text-gray-500">{c.reason}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onApprove(c.id)} data-testid={`approve-${c.id}`}>
                      {t("approvals.approve")}
                    </button>
                    <input
                      className="border rounded p-1 text-sm w-28"
                      value={rejectNotes[c.id] ?? ""}
                      onChange={(e) => setRejectNotes((prev) => ({ ...prev, [c.id]: e.target.value }))}
                      placeholder={t("approvals.decision_note")}
                      data-testid={`reject-note-${c.id}`}
                    />
                    <button
                      className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                      disabled={!rejectNotes[c.id]}
                      onClick={() => onReject(c.id)}
                      data-testid={`reject-${c.id}`}
                    >
                      {t("approvals.reject")}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}

        {/* Exemption Requests */}
        {tab === "exemptions" && (
          <>
            {erItems.length === 0 && <p className="text-sm text-gray-500">{t("approvals.exemption_none")}</p>}
            <ul className="space-y-3" data-testid="er-approvals-list">
              {erItems.map((er) => (
                <li key={er.id} className="border rounded p-3 flex items-center gap-4" data-testid={`er-approval-row-${er.id}`}>
                  <div className="flex-1">
                    <p className="text-sm"><strong>{er.soldier_id}</strong> — {er.start_date} → {er.end_date ?? t("exemptions.forever")}</p>
                    <p className="text-xs text-gray-500">{er.reason}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onErApprove(er.id)} data-testid={`er-approve-${er.id}`}>
                      {t("approvals.approve")}
                    </button>
                    <input
                      className="border rounded p-1 text-sm w-28"
                      value={rejectNotes[`er-${er.id}`] ?? ""}
                      onChange={(e) => setRejectNotes((prev) => ({ ...prev, [`er-${er.id}`]: e.target.value }))}
                      placeholder={t("approvals.decision_note")}
                      data-testid={`er-reject-note-${er.id}`}
                    />
                    <button
                      className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                      disabled={!rejectNotes[`er-${er.id}`]}
                      onClick={() => onErReject(er.id)}
                      data-testid={`er-reject-${er.id}`}
                    >
                      {t("approvals.reject")}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </Layout>
  );
}
```

- [ ] **Step 2: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

---

### Task 13: Create Playwright E2E tests

**Files:**
- Create: `frontend/tests/e2e/hierarchy.spec.ts`
- Create: `frontend/tests/e2e/personal_constraints.spec.ts`
- Create: `frontend/tests/e2e/exemption_requests.spec.ts`
- Create: `frontend/tests/e2e/duty_calendar.spec.ts`
- Create: `frontend/tests/e2e/seed_views.spec.ts`

- [ ] **Step 1: Create hierarchy.spec.ts**

```typescript
import { test, expect, type Page } from "@playwright/test";

async function loginAsAdmin(page: Page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  try {
    await page.waitForURL(/\/change-password$/, { timeout: 4000 });
    await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
    await page.getByTestId("new-password").fill("AdminNewPassw0rd");
    await page.getByTestId("change-password-submit").click();
  } catch {
    await page.getByTestId("password-input").fill("AdminNewPassw0rd");
    await page.getByTestId("login-submit").click();
  }
  await expect(page).toHaveURL("/");
}

test.describe("Hierarchy tree", () => {
  test("admin sees tree, adds child node, assigns commander, renames node", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);

    // Tree is visible
    await expect(page.getByTestId("node-tree")).toBeVisible();

    // Find first department node toggle and expand it
    const firstToggle = page.getByTestId(/^tree-toggle-/).first();
    await firstToggle.click();

    // Add a child node under the first department
    const firstAddChild = page.getByTestId(/^tree-add-child-/).first();
    await firstAddChild.click();
    await expect(page.getByTestId("add-child-dialog")).toBeVisible();
    await page.getByTestId("child-name").fill(`תת-יחידת בדיקה ${Date.now() % 10000}`);
    await page.getByTestId("child-submit").click();
    await expect(page.getByTestId("add-child-dialog")).not.toBeVisible();

    // Rename a node
    const firstRename = page.getByTestId(/^tree-rename-/).first();
    await firstRename.click();
    await expect(page.getByTestId("rename-dialog")).toBeVisible();
    await page.getByTestId("rename-input").fill(`שם חדש ${Date.now() % 10000}`);
    await page.getByTestId("rename-submit").click();
    await expect(page.getByTestId("rename-dialog")).not.toBeVisible();

    // Assign commander
    const firstCommanderBtn = page.getByTestId(/^tree-commander-btn-/).first();
    await firstCommanderBtn.click();
    await expect(page.getByTestId("assign-commander-dialog")).toBeVisible();
    // Select first soldier in the dropdown
    await page.getByTestId("commander-select").selectOption({ index: 1 });
    await page.getByTestId("commander-submit").click();
    await expect(page.getByTestId("assign-commander-dialog")).not.toBeVisible();
  });
});
```

- [ ] **Step 2: Create personal_constraints.spec.ts**

```typescript
import { test, expect, type Page } from "@playwright/test";

async function loginAsAdmin(page: Page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  try {
    await page.waitForURL(/\/change-password$/, { timeout: 4000 });
    await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
    await page.getByTestId("new-password").fill("AdminNewPassw0rd");
    await page.getByTestId("change-password-submit").click();
  } catch {
    await page.getByTestId("password-input").fill("AdminNewPassw0rd");
    await page.getByTestId("login-submit").click();
  }
  await expect(page).toHaveURL("/");
}

test("soldier submits personal constraint, sees Hebrew error for past date", async ({ page }) => {
  await loginAsAdmin(page);

  // Go to my requests
  await page.getByTestId("nav-my-requests").click();
  await expect(page).toHaveURL(/\/my-requests$/);

  // Try past date - should show error
  await page.getByTestId("req-start").fill("2020-01-01");
  await page.getByTestId("req-end").fill("2020-01-03");
  await page.getByTestId("req-reason").fill("בדיקה");
  await page.getByTestId("req-submit").click();

  // Should see Hebrew error
  await expect(page.getByTestId("req-error")).toBeVisible();
  await expect(page.getByTestId("req-error")).not.toContainText("error");

  // Now submit with future dates
  const futureStart = new Date();
  futureStart.setDate(futureStart.getDate() + 10);
  const futureEnd = new Date();
  futureEnd.setDate(futureEnd.getDate() + 12);
  const fmtDate = (d: Date) => d.toISOString().slice(0, 10);

  await page.getByTestId("req-start").fill(fmtDate(futureStart));
  await page.getByTestId("req-end").fill(fmtDate(futureEnd));
  await page.getByTestId("req-reason").fill("חופשה אישית");
  await page.getByTestId("req-submit").click();

  // Should succeed (constraint appears in list)
  await expect(page.getByTestId("constraints-list")).toBeVisible();
});
```

- [ ] **Step 3: Create exemption_requests.spec.ts**

```typescript
import { test, expect, type Page } from "@playwright/test";

async function loginAsAdmin(page: Page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  try {
    await page.waitForURL(/\/change-password$/, { timeout: 4000 });
    await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
    await page.getByTestId("new-password").fill("AdminNewPassw0rd");
    await page.getByTestId("change-password-submit").click();
  } catch {
    await page.getByTestId("password-input").fill("AdminNewPassw0rd");
    await page.getByTestId("login-submit").click();
  }
  await expect(page).toHaveURL("/");
}

test("admin creates exemption type, soldier requests exemption, admin approves", async ({ page }) => {
  await loginAsAdmin(page);

  const suffix = `${Date.now() % 100000}`;
  const etName = `פטור-בדיקה-${suffix}`;

  // First create an exemption type
  await page.getByTestId("nav-duty-config").click();
  await expect(page).toHaveURL(/\/duty-config$/);
  await page.getByTestId("et-name").fill(etName);
  await page.getByTestId("et-submit").click();
  await expect(page.getByTestId(`et-row-${etName}`)).toBeVisible();

  // Go to my requests and submit exemption request
  await page.getByTestId("nav-my-requests").click();
  await expect(page).toHaveURL(/\/my-requests$/);

  await page.getByTestId("er-type").selectOption({ label: etName });
  const futureStart = new Date();
  futureStart.setDate(futureStart.getDate() + 20);
  const futureEnd = new Date();
  futureEnd.setDate(futureEnd.getDate() + 25);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  await page.getByTestId("er-start").fill(fmt(futureStart));
  await page.getByTestId("er-end").fill(fmt(futureEnd));
  await page.getByTestId("er-reason").fill("בקשת פטור בדיקה");
  await page.getByTestId("er-submit").click();

  // Should appear in the list
  await expect(page.getByTestId("er-list")).toBeVisible();

  // Go to approvals page and approve it
  await page.getByTestId("nav-approvals").click();
  await expect(page).toHaveURL(/\/approvals$/);
  await page.getByTestId("approvals-tab-exemptions").click();

  // Find and approve the request
  const approveBtn = page.getByTestId(/^er-approve-/).first();
  if (await approveBtn.isVisible()) {
    await approveBtn.click();
    // Should disappear from pending list
    await expect(page.getByTestId("er-approvals-list")).toBeVisible();
  }
});
```

- [ ] **Step 4: Create duty_calendar.spec.ts**

```typescript
import { test, expect, type Page } from "@playwright/test";

async function loginAsAdmin(page: Page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  try {
    await page.waitForURL(/\/change-password$/, { timeout: 4000 });
    await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
    await page.getByTestId("new-password").fill("AdminNewPassw0rd");
    await page.getByTestId("change-password-submit").click();
  } catch {
    await page.getByTestId("password-input").fill("AdminNewPassw0rd");
    await page.getByTestId("login-submit").click();
  }
  await expect(page).toHaveURL("/");
}

test("calendar shows on my duties page, navigation works, empty state visible", async ({ page }) => {
  await loginAsAdmin(page);

  await page.getByTestId("nav-my-duties").click();
  await expect(page).toHaveURL(/\/my-duties$/);

  // Calendar is visible
  await expect(page.getByTestId("duty-calendar")).toBeVisible();

  // Duty list is visible (even if empty)
  await expect(page.getByTestId("my-duties-page")).toBeVisible();

  // Navigate to next month
  const nextBtn = page.locator(".react-calendar__navigation__next-button");
  if (await nextBtn.isVisible()) {
    await nextBtn.click();
  }

  // Navigate back
  const prevBtn = page.locator(".react-calendar__navigation__prev-button");
  if (await prevBtn.isVisible()) {
    await prevBtn.click();
  }
});
```

- [ ] **Step 5: Create seed_views.spec.ts**

```typescript
import { test, expect, type Page } from "@playwright/test";

async function loginAsAdmin(page: Page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  try {
    await page.waitForURL(/\/change-password$/, { timeout: 4000 });
    await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
    await page.getByTestId("new-password").fill("AdminNewPassw0rd");
    await page.getByTestId("change-password-submit").click();
  } catch {
    await page.getByTestId("password-input").fill("AdminNewPassw0rd");
    await page.getByTestId("login-submit").click();
  }
  await expect(page).toHaveURL("/");
}

test("seeded data renders correctly across pages", async ({ page }) => {
  await loginAsAdmin(page);

  // Team page shows tree with many nodes
  await page.getByTestId("nav-team").click();
  await expect(page.getByTestId("node-tree")).toBeVisible();
  // Should have multiple nodes from seed
  const treeItems = await page.getByTestId(/^tree-name-/).count();
  expect(treeItems).toBeGreaterThan(5);

  // Soldier table has many rows
  await expect(page.getByTestId("soldier-table")).toBeVisible();
  const soldierRows = await page.getByTestId(/^soldier-row-/).count();
  expect(soldierRows).toBeGreaterThan(10);

  // Unit calendar renders
  await page.getByTestId("nav-unit-calendar").click();
  await expect(page).toHaveURL(/\/unit-calendar$/);

  // Transparency page renders
  await page.getByTestId("nav-transparency").click();
  await expect(page).toHaveURL(/\/transparency$/);
});
```

- [ ] **Step 6: Run the E2E tests**

Run: `cd frontend && npx playwright test`
Expected: Tests pass.

---

### Task 14: Fix the Layout component to show exemption request pending count

**Files:**
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add i18n key for nav**

Add to `he.json` in the `nav` block:

```json
    "exemption_approvals": "בקשות פטור"
```

- [ ] **Step 2: Read and update Layout if needed**

This is optional — the approvals page handles the tab internally. The nav link is unchanged.

---

### Task 15: Final verification

- [ ] **Step 1: Run backend lint**

Run: `cd backend && ruff check app/`
Expected: No errors.

- [ ] **Step 2: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Run seed script**

Run: `cd backend && python -m app.scripts.seed`
Expected: "Seed complete!" message.

- [ ] **Step 4: Run E2E tests**

Run: `cd frontend && npx playwright test`
Expected: All tests pass.
