# Unit Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the text-table UnitCalendarPage with a FullCalendar month view showing duties as visual blocks, with multi-day spanning and a clickable detail table below.

**Architecture:** Backend enriches `/api/calendar/unit` with duty type/location names + color. Frontend uses FullCalendar's `dayGridMonth` view to render duties as events, with `dateClick`/`eventClick` handlers populating a detail table below.

**Tech Stack:** FullCalendar v6 (`@fullcalendar/react`, `@fullcalendar/daygrid`, `@fullcalendar/interaction`), FastAPI, Pydantic, react-calendar (removed from UnitCalendarPage), TypeScript

---

### Task 1: Backend — enrich `/api/calendar/unit` with names and color

**Files:**
- Modify: `backend/app/routes/calendar.py`

- [ ] **Step 1: Update CalAssignment model**

Add `duty_type_name`, `duty_location_name`, and `duty_type_color` fields:

Edit `backend/app/routes/calendar.py`:

```python
class CalAssignment(BaseModel):
    assignment_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    duty_type_color: str
    duty_location_id: uuid.UUID
    duty_location_name: str
    start_date: date
    end_date: date
```

- [ ] **Step 2: Update import to include DutyType and DutyLocation**

In `backend/app/routes/calendar.py`, add `DutyType` and `DutyLocation` to the import from `app.db.models`:

```python
from app.db.models import DutyLocation, DutyType, HierarchyNode, Soldier
```

- [ ] **Step 3: Add color helper function and name resolution in `unit_calendar` endpoint**

Add a color hash function before the router:

```python
def _duty_type_color(duty_type_id: uuid.UUID) -> str:
    h = hash(duty_type_id) % 360
    return f"hsl({h}, 65%, 55%)"
```

In `unit_calendar`, after fetching soldiers, load duty types and locations into dicts:

```python
    soldier_ids = [s.id for s in soldiers]
    duty_types = {dt.id: dt for dt in session.execute(select(DutyType)).scalars().all()}
    duty_locations = {dl.id: dl for dl in session.execute(select(DutyLocation)).scalars().all()}
    spans = scoring_svc.effective_duty_spans(...)
```

Then in the CalAssignment construction, add the name fields:

```python
    for sp in spans:
        dt_id = sp["duty_type_id"]
        dl_id = sp["duty_location_id"]
        dt = duty_types.get(dt_id)
        dl = duty_locations.get(dl_id)
        by_soldier[sp["soldier_id"]].append(
            CalAssignment(
                assignment_id=sp["assignment_id"],
                duty_type_id=dt_id,
                duty_type_name=dt.name if dt else "?",
                duty_type_color=_duty_type_color(dt_id),
                duty_location_id=dl_id,
                duty_location_name=dl.name if dl else "?",
                start_date=sp["start_date"],
                end_date=sp["end_date"],
            )
        )
```

- [ ] **Step 4: Run ruff lint**

```bash
cd backend; .venv/Scripts/ruff check app/routes/calendar.py
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/calendar.py
git commit -m "feat: enrich calendar API with duty type/location names and color"
```

---

### Task 2: Frontend — update CalAssignment type and install FullCalendar

**Files:**
- Modify: `frontend/src/api/calendar.ts`

- [ ] **Step 1: Update `CalAssignment` interface**

Edit `frontend/src/api/calendar.ts` to add the new fields:

```typescript
export interface CalAssignment {
  assignment_id: string;
  duty_type_id: string;
  duty_type_name: string;
  duty_type_color: string;
  duty_location_id: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
}
```

- [ ] **Step 2: Install FullCalendar dependencies**

```bash
cd frontend; pnpm add @fullcalendar/react @fullcalendar/daygrid @fullcalendar/interaction
```

Expected: packages installed successfully.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/calendar.ts frontend/package.json frontend/pnpm-lock.yaml
git commit -m "feat: extend calendar API types, add FullCalendar deps"
```

---

### Task 3: Frontend — create UnitCalendar component

**Files:**
- Create: `frontend/src/components/UnitCalendar.tsx`

- [ ] **Step 1: Write the component shell**

Create `frontend/src/components/UnitCalendar.tsx`:

```typescript
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import heLocale from "@fullcalendar/core/locales/he";
import type { EventClickArg, DatesSetArg } from "@fullcalendar/core";

import { CalRow, CalAssignment, getUnitCalendar } from "../api/calendar";

interface UnitCalendarProps {
  nodeId: string;
}

export default function UnitCalendar({ nodeId }: UnitCalendarProps) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<CalRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<{
    assignment: CalAssignment;
    soldier_name: string;
  } | null>(null);
  const [dutyTypeFilter, setDutyTypeFilter] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<{ from: string; to: string } | null>(null);

  const fetchData = useCallback(async (from: string, to: string) => {
    if (!nodeId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getUnitCalendar(nodeId, { date_from: from, date_to: to });
      setRows(data);
    } catch {
      setError(t("unit_calendar.error") || "Failed to load calendar");
    } finally {
      setLoading(false);
    }
  }, [nodeId, t]);

  useEffect(() => {
    if (dateRange) fetchData(dateRange.from, dateRange.to);
  }, [dateRange, fetchData]);

  function handleDatesSet(arg: DatesSetArg) {
    const from = arg.start.toISOString().slice(0, 10);
    const to = arg.end.toISOString().slice(0, 10);
    setDateRange({ from, to });
  }

  const events = useMemo(() => {
    const out: {
      id: string;
      title: string;
      start: string;
      end: string;
      backgroundColor: string;
      borderColor: string;
      extendedProps: { soldier_name: string; duty_type_id: string; duty_location_name: string; soldier_id: string; assignment_id: string };
    }[] = [];
    for (const r of rows) {
      for (const a of r.assignments) {
        const endDate = new Date(a.end_date);
        endDate.setDate(endDate.getDate() + 1);
        out.push({
          id: `${a.assignment_id}-${a.start_date}`,
          title: a.duty_type_name,
          start: a.start_date,
          end: endDate.toISOString().slice(0, 10),
          backgroundColor: a.duty_type_color,
          borderColor: a.duty_type_color,
          extendedProps: {
            soldier_name: r.full_name,
            duty_type_id: a.duty_type_id,
            duty_location_name: a.duty_location_name,
            soldier_id: r.soldier_id,
            assignment_id: a.assignment_id,
          },
        });
      }
    }
    return out;
  }, [rows]);

  function handleDateClick(arg: { dateStr: string }) {
    setSelectedDate(arg.dateStr);
    setSelectedEvent(null);
  }

  function handleEventClick(arg: EventClickArg) {
    const props = arg.event.extendedProps;
    const endStr = arg.event.endStr || arg.event.startStr;
    const endDate = new Date(endStr);
    endDate.setDate(endDate.getDate() - 1);
    setSelectedEvent({
      soldier_name: props.soldier_name,
      assignment: {
        assignment_id: props.assignment_id,
        duty_type_id: props.duty_type_id,
        duty_type_name: arg.event.title,
        duty_type_color: arg.event.backgroundColor,
        duty_location_id: "",
        duty_location_name: props.duty_location_name,
        start_date: arg.event.startStr.slice(0, 10),
        end_date: endDate.toISOString().slice(0, 10),
      },
    });
    setSelectedDate(null);
  }

  const detailRows = useMemo(() => {
    const date = selectedDate;
    if (!date) return null;
    const out: { soldier_name: string; duty_type_name: string; duty_location_name: string }[] = [];
    for (const r of rows) {
      for (const a of r.assignments) {
        if (a.start_date <= date && a.end_date >= date) {
          if (dutyTypeFilter && a.duty_type_id !== dutyTypeFilter) continue;
          out.push({ soldier_name: r.full_name, duty_type_name: a.duty_type_name, duty_location_name: a.duty_location_name });
        }
      }
    }
    out.sort((a, b) => a.soldier_name.localeCompare(b.soldier_name));
    return out;
  }, [rows, selectedDate, dutyTypeFilter]);

  function toggleFilter(dtId: string) {
    setDutyTypeFilter((prev) => (prev === dtId ? null : dtId));
  }

  // Collect unique duty types from currently displayed data for filter chips
  const dutyTypesInView = useMemo(() => {
    const seen = new Map<string, string>();
    for (const r of rows) {
      for (const a of r.assignments) {
        if (!seen.has(a.duty_type_id)) seen.set(a.duty_type_id, a.duty_type_name);
      }
    }
    return Array.from(seen.entries()).map(([id, name]) => ({ id, name }));
  }, [rows]);

  return (
    <div className="space-y-4">
      {/* Filter chips */}
      {dutyTypesInView.length > 1 && (
        <div className="flex flex-wrap gap-2 text-sm">
          <span className="text-gray-500">{t("unit_calendar.filter_label") || "סינון:"}</span>
          {dutyTypesInView.map((dt) => (
            <button
              key={dt.id}
              onClick={() => toggleFilter(dt.id)}
              data-testid={`filter-chip-${dt.id}`}
              className={`px-2 py-1 rounded-full border text-xs ${
                dutyTypeFilter === dt.id ? "bg-indigo-100 border-indigo-400 text-indigo-700" : "bg-white border-gray-300 text-gray-600"
              }`}
            >
              {dt.name}
            </button>
          ))}
        </div>
      )}

      {/* Calendar */}
      {loading && <p className="text-gray-500 text-sm">{t("unit_calendar.loading")}</p>}
      {error && <p className="text-red-500 text-sm" data-testid="unit-calendar-error">{error}</p>}
      <div data-testid="fullcalendar" className="text-sm">
        <FullCalendar
          plugins={[dayGridPlugin, interactionPlugin]}
          initialView="dayGridMonth"
          events={events}
          dateClick={handleDateClick}
          eventClick={handleEventClick}
          datesSet={handleDatesSet}
          locales={[heLocale]}
          locale="he"
          height="auto"
          headerToolbar={{ left: "prev,next today", center: "title", right: "dayGridMonth" }}
          buttonText={{ today: t("unit_calendar.today") || "היום" }}
          noEventsText={t("unit_calendar.none")}
          eventTimeDisplay=""
        />
      </div>

      {/* Detail table */}
      <div data-testid="calendar-detail" className="bg-white rounded-lg border p-4">
        {selectedEvent ? (
          <div>
            <h3 className="font-semibold mb-2">{t("unit_calendar.duty_detail") || "פרטי תורנות"}</h3>
            <table className="w-full text-sm text-right">
              <tbody>
                <tr className="border-b"><td className="p-1 font-medium">{t("unit_calendar.soldier")}</td><td className="p-1">{selectedEvent.soldier_name}</td></tr>
                <tr className="border-b"><td className="p-1 font-medium">{t("unit_calendar.duty_type") || "סוג תורנות"}</td><td className="p-1">{selectedEvent.assignment.duty_type_name}</td></tr>
                <tr className="border-b"><td className="p-1 font-medium">{t("unit_calendar.location") || "מיקום"}</td><td className="p-1">{selectedEvent.assignment.duty_location_name}</td></tr>
                <tr className="border-b"><td className="p-1 font-medium">{t("unit_calendar.from") || "מתאריך"}</td><td className="p-1">{selectedEvent.assignment.start_date}</td></tr>
                <tr><td className="p-1 font-medium">{t("unit_calendar.to") || "עד תאריך"}</td><td className="p-1">{selectedEvent.assignment.end_date}</td></tr>
              </tbody>
            </table>
          </div>
        ) : detailRows ? (
          <div>
            <h3 className="font-semibold mb-2">
              {t("unit_calendar.detail_table") || "תורנויות לתאריך"}
              {selectedDate && ` — ${selectedDate}`}
              {dutyTypeFilter && ` (${dutyTypesInView.find((d) => d.id === dutyTypeFilter)?.name})`}
            </h3>
            {detailRows.length === 0 ? (
              <p className="text-gray-500 text-sm">{t("unit_calendar.none")}</p>
            ) : (
              <table className="w-full text-sm text-right" data-testid="detail-table">
                <thead>
                  <tr className="border-b">
                    <th className="p-1">{t("unit_calendar.soldier")}</th>
                    <th className="p-1">{t("unit_calendar.duty_type") || "סוג תורנות"}</th>
                    <th className="p-1">{t("unit_calendar.location") || "מיקום"}</th>
                  </tr>
                </thead>
                <tbody>
                  {detailRows.map((r, i) => (
                    <tr key={i} className="border-b last:border-0" data-testid={`detail-row-${i}`}>
                      <td className="p-1">{r.soldier_name}</td>
                      <td className="p-1">{r.duty_type_name}</td>
                      <td className="p-1">{r.duty_location_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ) : (
          <p className="text-gray-400 text-sm">{t("unit_calendar.click_hint")}</p>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify type check**

Run: `cd frontend; npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/UnitCalendar.tsx
git commit -m "feat: create UnitCalendar component with FullCalendar month view"
```

---

### Task 4: Frontend — update UnitCalendarPage to use new component

**Files:**
- Modify: `frontend/src/pages/UnitCalendarPage.tsx`

- [ ] **Step 1: Replace content**

Edit `frontend/src/pages/UnitCalendarPage.tsx` to use the new `UnitCalendar` component instead of the inline table:

```typescript
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import UnitCalendar from "../components/UnitCalendar";
import { NodeDTO, fetchTree } from "../api/hierarchy";

export default function UnitCalendarPage() {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [nodeId, setNodeId] = useState<string>("");

  useEffect(() => { void fetchTree().then((ns) => { setNodes(ns); if (ns[0]) setNodeId(ns[0].id); }); }, []);

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="unit-calendar-page">
        <h2 className="text-xl font-semibold">{t("unit_calendar.title")}</h2>
        <select className="border rounded p-1" value={nodeId} onChange={(e) => setNodeId(e.target.value)} data-testid="unit-node-select">
          {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
        </select>
        {nodeId ? <UnitCalendar nodeId={nodeId} /> : <p data-testid="unit-calendar-empty">{t("unit_calendar.none")}</p>}
      </section>
    </Layout>
  );
}
```

- [ ] **Step 2: Run type check**

Run: `cd frontend; npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/UnitCalendarPage.tsx
git commit -m "feat: use UnitCalendar component in UnitCalendarPage"
```

---

### Task 5: Frontend — update i18n keys

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add unit_calendar keys**

Edit `frontend/src/i18n/he.json` to add new keys under the existing `unit_calendar` block (replacing the old ones):

```json
  "unit_calendar": {
    "title": "יומן יחידה",
    "today": "היום",
    "soldier": "חייל",
    "duty_type": "סוג תורנות",
    "location": "מיקום",
    "from": "מתאריך",
    "to": "עד תאריך",
    "duties": "תורנויות",
    "none": "אין תורנויות",
    "loading": "טוען יומן...",
    "error": "שגיאה בטעינת היומן",
    "detail_table": "פירוט תורנויות לתאריך",
    "click_hint": "לחץ על יום או תורנות לפרטים",
    "duty_detail": "פרטי תורנות",
    "filter_label": "סינון לפי סוג:"
  }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "feat: update unit_calendar i18n keys"
```

---

### Task 6: E2E tests

**Files:**
- Modify: `frontend/tests/e2e/seed_views.spec.ts`

- [ ] **Step 1: Update the seed views test**

Edit `frontend/tests/e2e/seed_views.spec.ts`. Replace or extend the existing unit calendar test section:

```typescript
// In the unit calendar test section
test("unit calendar shows FullCalendar with duties", async ({ page }) => {
  await page.goto("/unit-calendar");
  await page.waitForSelector('[data-testid="unit-calendar-page"]');

  // Hierarchy dropdown should be populated
  const select = page.locator('[data-testid="unit-node-select"]');
  await expect(select).toBeVisible();
  const options = select.locator("option");
  await expect(options).toHaveCount(30); // 30 hierarchy nodes from seed

  // FullCalendar should render
  await page.waitForSelector('[data-testid="fullcalendar"]');
  await expect(page.locator(".fc-dayGridMonth-view")).toBeVisible();

  // Click a day and verify detail table appears
  const dayCell = page.locator(".fc-daygrid-day").first();
  if (await dayCell.isVisible()) {
    await dayCell.click();
    // Either detail table or empty state shows
    await page.waitForTimeout(500);
    const table = page.locator('[data-testid="detail-table"]');
    const empty = page.locator("text=אין תורנויות");
    await expect(table.or(empty)).toBeVisible();
  }
});
```

- [ ] **Step 2: Run the E2E test to verify it parses**

Run: `cd frontend; npx playwright test tests/e2e/seed_views.spec.ts --list`

Expected: test appears in the list.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/seed_views.spec.ts
git commit -m "test: update unit calendar E2E tests for FullCalendar"
```

---

### Task 7: Full verification

- [ ] **Step 1: Run frontend type check**

```bash
cd frontend; npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 2: Run backend lint**

```bash
cd backend; .venv/Scripts/ruff check app/routes/calendar.py
```

Expected: no lint errors.

- [ ] **Step 3: Run E2E test list**

```bash
cd frontend; npx playwright test tests/e2e/seed_views.spec.ts --list
```

Expected: test listed.

- [ ] **Step 4: Final commit if any fixes**

```bash
git add -A
git commit -m "chore: fix review issues in unit calendar"
```
