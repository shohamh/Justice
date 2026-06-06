# Plan A — Homepage Dashboard Polish

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every homepage widget interactive and informative, fix multi-week calendar highlight, and add Israeli holidays as reference events.

**Architecture:** All changes are frontend-only except the `/calendar/holidays` endpoint. Shared duty-detail modal is lifted to `HomePage` state so both the calendar and upcoming-duties widget share one instance. The `holidays` Python package provides Israeli holiday data.

**Tech Stack:** React, FullCalendar, Tailwind, FastAPI, `holidays` Python package

---

### Task 1: Add `holidays` Python package and endpoint

**Files:**
- Modify: `backend/pyproject.toml` (add `holidays` dependency)
- Create: `backend/app/routes/calendar_holidays.py`
- Modify: `backend/app/main.py` (register router)

- [ ] **Step 1: Add dependency**

In `backend/pyproject.toml`, under `[project] dependencies`, add:
```toml
"holidays>=0.46",
```

- [ ] **Step 2: Run `uv sync` to install**

```bash
cd backend && uv sync
```
Expected: resolves and installs `holidays`.

- [ ] **Step 3: Create the route**

Create `backend/app/routes/calendar_holidays.py`:
```python
from __future__ import annotations

from fastapi import APIRouter
import holidays as hol

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/holidays")
def list_holidays(year: int) -> list[dict]:
    il = hol.country_holidays("IL", years=year)
    return [{"date": str(d), "name": name} for d, name in sorted(il.items())]
```

- [ ] **Step 4: Register router in `backend/app/main.py`**

Find the block where other routers are included (look for `app.include_router`) and add:
```python
from app.routes.calendar_holidays import router as holidays_router
app.include_router(holidays_router)
```

- [ ] **Step 5: Verify endpoint manually**

```bash
curl "http://localhost:8000/calendar/holidays?year=2026"
```
Expected: JSON array with entries like `{"date": "2026-09-20", "name": "Rosh Hashana"}`.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/routes/calendar_holidays.py backend/app/main.py
git commit -m "feat: add GET /calendar/holidays endpoint using holidays package"
```

---

### Task 2: Add `formatDate` utility and holiday API call

**Files:**
- Create: `frontend/src/utils/formatDate.ts`
- Create: `frontend/src/api/calendarHolidays.ts`

- [ ] **Step 1: Create `formatDate` utility**

Create `frontend/src/utils/formatDate.ts`:
```ts
export function formatDate(d: string | Date): string {
  const date = typeof d === "string" ? new Date(d + "T00:00:00") : d;
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const yyyy = date.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

export function formatDateRange(start: string | Date, end: string | Date): string {
  const s = typeof start === "string" ? start : start.toISOString().split("T")[0];
  const e = typeof end === "string" ? end : end.toISOString().split("T")[0];
  if (s === e) return formatDate(s);
  return `${formatDate(s)} – ${formatDate(e)}`;
}
```

- [ ] **Step 2: Create holidays API wrapper**

Create `frontend/src/api/calendarHolidays.ts`:
```ts
import { api } from "./client";

export interface Holiday {
  date: string;
  name: string;
}

export async function listHolidays(year: number): Promise<Holiday[]> {
  return (await api.get<Holiday[]>("/calendar/holidays", { params: { year } })).data;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/formatDate.ts frontend/src/api/calendarHolidays.ts
git commit -m "feat: add formatDate utility and holidays API client"
```

---

### Task 3: Duty detail modal — shared state in HomePage

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`
- Create: `frontend/src/components/dashboard/DutyDetailModal.tsx`

- [ ] **Step 1: Create `DutyDetailModal`**

Create `frontend/src/components/dashboard/DutyDetailModal.tsx`:
```tsx
import { EffectiveDuty } from "../../api/assignments";

interface Props {
  duty: EffectiveDuty | null;
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
  onClose: () => void;
  onRequestSwap: (duty: EffectiveDuty) => void;
}

export default function DutyDetailModal({ duty, typeNames, locationNames, onClose, onRequestSwap }: Props) {
  if (!duty) return null;
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-sm w-full mx-4 space-y-3"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="text-lg font-semibold">פרטי תורנות</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>
        <dl className="text-sm space-y-1">
          <div className="flex gap-2">
            <dt className="text-gray-500 w-20 shrink-0">סוג</dt>
            <dd>{typeNames[duty.duty_type_id] ?? "—"}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-gray-500 w-20 shrink-0">מיקום</dt>
            <dd>{locationNames[duty.duty_location_id] ?? "—"}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-gray-500 w-20 shrink-0">תאריכים</dt>
            <dd dir="ltr">{duty.start_date === duty.end_date ? duty.start_date : `${duty.start_date} – ${duty.end_date}`}</dd>
          </div>
        </dl>
        <button
          className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-2 rounded text-sm font-medium"
          onClick={() => onRequestSwap(duty)}
        >
          בקש החלפה
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add modal state to `HomePage`**

In `frontend/src/pages/HomePage.tsx`, add:
```tsx
import DutyDetailModal from "../components/dashboard/DutyDetailModal";

// inside HomePage, add state:
const [selectedDuty, setSelectedDuty] = useState<EffectiveDuty | null>(null);

function handleOpenDuty(duty: EffectiveDuty) {
  setSelectedDuty(duty);
}

function handleRequestSwap(duty: EffectiveDuty) {
  setSelectedDuty(null);
  // navigate to swap creation — link to swaps page with assignment id
  window.location.href = `/swaps?new=${duty.assignment_id}`;
}
```

Add at bottom of JSX, before closing `</Layout>`:
```tsx
<DutyDetailModal
  duty={selectedDuty}
  typeNames={typeNames}
  locationNames={locationNames}
  onClose={() => setSelectedDuty(null)}
  onRequestSwap={handleRequestSwap}
/>
```

Also pass `onOpenDuty={handleOpenDuty}` to both `DutyCalendarWidget` and `UpcomingDutiesWidget`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/DutyDetailModal.tsx frontend/src/pages/HomePage.tsx
git commit -m "feat: add shared DutyDetailModal to HomePage with swap action"
```

---

### Task 4: Wire calendar eventClick + holidays

**Files:**
- Modify: `frontend/src/components/dashboard/DutyCalendarWidget.tsx`

- [ ] **Step 1: Update `DutyCalendarWidget`**

Replace the file content with:
```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import heLocale from "@fullcalendar/core/locales/he";
import { EffectiveDuty } from "../../api/assignments";
import { Holiday, listHolidays } from "../../api/calendarHolidays";
import { dutyTypeColor } from "../../utils/dutyTypeColor";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  onOpenDuty: (duty: EffectiveDuty) => void;
}

export default function DutyCalendarWidget({ duties, typeNames, onOpenDuty }: Props) {
  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const hoveredIdRef = useRef<string | null>(null);

  useEffect(() => {
    const year = new Date().getFullYear();
    void listHolidays(year).then(setHolidays).catch(() => {});
  }, []);

  const dutyEvents = useMemo(() =>
    duties.map((d) => {
      const endDate = new Date(d.end_date + "T00:00:00");
      endDate.setDate(endDate.getDate() + 1);
      const color = dutyTypeColor(d.duty_type_id);
      return {
        id: d.assignment_id,
        title: typeNames[d.duty_type_id] ?? "תורנות",
        start: d.start_date,
        end: endDate.toISOString().split("T")[0],
        backgroundColor: color,
        borderColor: color,
        extendedProps: { duty: d },
      };
    }),
  [duties, typeNames]);

  const holidayEvents = useMemo(() =>
    holidays.map((h) => ({
      id: `holiday-${h.date}`,
      title: h.name,
      start: h.date,
      display: "background",
      backgroundColor: "#fef9c3",
      extendedProps: { isHoliday: true },
    })),
  [holidays]);

  function handleEventMouseEnter(info: { event: { id: string } }) {
    hoveredIdRef.current = info.event.id;
    document.querySelectorAll(`[data-event-id="${info.event.id}"]`).forEach((el) => {
      (el as HTMLElement).style.filter = "brightness(0.85)";
    });
  }

  function handleEventMouseLeave() {
    if (hoveredIdRef.current) {
      document.querySelectorAll(`[data-event-id="${hoveredIdRef.current}"]`).forEach((el) => {
        (el as HTMLElement).style.filter = "";
      });
      hoveredIdRef.current = null;
    }
  }

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">היומן שלי</h2>
      <FullCalendar
        plugins={[dayGridPlugin]}
        initialView="dayGridMonth"
        locale={heLocale}
        events={[...dutyEvents, ...holidayEvents]}
        headerToolbar={{ start: "prev,next", center: "title", end: "" }}
        height="auto"
        editable={false}
        selectable={false}
        eventClick={(info) => {
          if (info.event.extendedProps.isHoliday) return;
          const duty = info.event.extendedProps.duty as EffectiveDuty;
          onOpenDuty(duty);
        }}
        eventMouseEnter={handleEventMouseEnter}
        eventMouseLeave={handleEventMouseLeave}
      />
    </section>
  );
}
```

- [ ] **Step 2: Verify holidays render**

Start dev server, navigate to homepage. Confirm:
- Jewish holidays appear as yellow background events.
- Clicking a duty event opens the detail modal.
- Hovering a multi-week event highlights both segments.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/DutyCalendarWidget.tsx
git commit -m "feat: calendar duty click modal + multi-week hover + Israeli holidays"
```

---

### Task 5: Upcoming duties — clickable rows

**Files:**
- Modify: `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx`

- [ ] **Step 1: Update `UpcomingDutiesWidget`**

Replace file content:
```tsx
import { EffectiveDuty } from "../../api/assignments";
import { formatDateRange } from "../../utils/formatDate";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
  onOpenDuty: (duty: EffectiveDuty) => void;
}

export default function UpcomingDutiesWidget({ duties, typeNames, locationNames, onOpenDuty }: Props) {
  const today = new Date().toISOString().split("T")[0];
  const upcoming = duties
    .filter((d) => d.end_date >= today)
    .sort((a, b) => a.start_date.localeCompare(b.start_date));

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">תורנויות קרובות</h2>
      {upcoming.length === 0 ? (
        <p className="text-sm text-gray-500">אין תורנויות קרובות</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-gray-600">
              <th className="text-right pb-2 font-medium">תאריך</th>
              <th className="text-right pb-2 font-medium">סוג</th>
              <th className="text-right pb-2 font-medium">מיקום</th>
              <th className="pb-2 w-6"></th>
            </tr>
          </thead>
          <tbody>
            {upcoming.map((d) => (
              <tr
                key={d.assignment_id}
                className="border-b dark:border-gray-600 last:border-0 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700"
                onClick={() => onOpenDuty(d)}
              >
                <td className="py-2">{formatDateRange(d.start_date, d.end_date)}</td>
                <td className="py-2">{typeNames[d.duty_type_id] ?? "—"}</td>
                <td className="py-2">{locationNames[d.duty_location_id] ?? "—"}</td>
                <td className="py-2 text-gray-400 text-xs">›</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/dashboard/UpcomingDutiesWidget.tsx
git commit -m "feat: upcoming duties rows clickable, open duty detail modal"
```

---

### Task 6: Swap status widget — richer info

**Files:**
- Modify: `frontend/src/components/dashboard/SwapStatusWidget.tsx`

- [ ] **Step 1: Update `SwapStatusWidget`**

The `SwapRequest` already has `duty_type_name`, `duty_start_date`, `duty_end_date`. Update:
```tsx
import { Link } from "react-router-dom";
import { SwapRequest } from "../../api/swaps";
import { formatDateRange } from "../../utils/formatDate";

interface Props {
  swaps: SwapRequest[];
}

const STATUS_CHIPS: Record<string, string> = {
  open: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  pending_approval: "bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300",
  applied: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
  rejected: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
};

const STATUS_LABELS: Record<string, string> = {
  open: "פתוח",
  pending_approval: "ממתין לאישור",
  applied: "אושר",
  rejected: "נדחה",
};

export default function SwapStatusWidget({ swaps }: Props) {
  const active = swaps.filter((s) => s.status === "open" || s.status === "pending_approval");
  if (active.length === 0) return null;

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">ההחלפות שלי</h2>
        <Link to="/swaps" className="text-sm text-indigo-600 hover:text-indigo-800">
          לדף החלפות →
        </Link>
      </div>
      <ul className="space-y-2">
        {active.map((s) => (
          <li key={s.id} className="flex items-start justify-between text-sm border-b dark:border-gray-600 last:border-0 pb-2 last:pb-0 gap-2">
            <div className="space-y-0.5">
              <div className="font-medium">
                {s.duty_type_name ?? "תורנות"}
              </div>
              <div className="text-gray-500 text-xs">
                {s.duty_start_date && s.duty_end_date
                  ? formatDateRange(s.duty_start_date, s.duty_end_date)
                  : formatDateRange(s.duty_date, s.duty_date)}
              </div>
              {s.reason && <div className="text-gray-400 text-xs">{s.reason}</div>}
            </div>
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium shrink-0 ${STATUS_CHIPS[s.status] ?? "bg-gray-100 text-gray-600"}`}>
              {STATUS_LABELS[s.status] ?? s.status}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/dashboard/SwapStatusWidget.tsx
git commit -m "feat: swap widget shows duty type, date range, all statuses; title fix"
```

---

### Task 7: Pending approvals — all categories

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`
- Modify: `frontend/src/components/dashboard/PendingApprovalsWidget.tsx`

- [ ] **Step 1: Fetch all pending counts in `HomePage`**

In `frontend/src/pages/HomePage.tsx`, add imports:
```tsx
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
```

Add state:
```tsx
const [pendingConstraints, setPendingConstraints] = useState(0);
const [pendingExemptions, setPendingExemptions] = useState(0);
const [pendingFieldUpdates, setPendingFieldUpdates] = useState(0);
```

In the `useEffect` fetch block (inside the `canApprove` guard), add:
```tsx
const constraintsFetch = canApprove
  ? getPendingCount().catch(() => 0)
  : Promise.resolve(0);
const exemptionsFetch = canApprove
  ? getPendingExemptionCount().catch(() => 0)
  : Promise.resolve(0);
const fieldUpdatesFetch = canApprove
  ? getPendingFieldUpdateCount().catch(() => 0)
  : Promise.resolve(0);
```

Include in `Promise.all` and set state:
```tsx
setPendingConstraints(constraints as number);
setPendingExemptions(exemptions as number);
setPendingFieldUpdates(fieldUpdates as number);
```

Pass to widget:
```tsx
<PendingApprovalsWidget
  pendingEnrollments={pendingEnrollments}
  pendingSwaps={pendingSwaps}
  pendingConstraints={pendingConstraints}
  pendingExemptions={pendingExemptions}
  pendingFieldUpdates={pendingFieldUpdates}
/>
```

- [ ] **Step 2: Update `PendingApprovalsWidget`**

Replace `frontend/src/components/dashboard/PendingApprovalsWidget.tsx`:
```tsx
import { Link } from "react-router-dom";
import { EnrollmentRequestDTO } from "../../api/enrollment";
import { SwapRequest } from "../../api/swaps";

interface Props {
  pendingEnrollments: EnrollmentRequestDTO[];
  pendingSwaps: SwapRequest[];
  pendingConstraints: number;
  pendingExemptions: number;
  pendingFieldUpdates: number;
}

function CountChip({ n }: { n: number }) {
  return (
    <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium text-xs">
      {n}
    </span>
  );
}

export default function PendingApprovalsWidget({
  pendingEnrollments, pendingSwaps, pendingConstraints, pendingExemptions, pendingFieldUpdates,
}: Props) {
  const total = pendingEnrollments.length + pendingSwaps.length + pendingConstraints + pendingExemptions + pendingFieldUpdates;
  if (total === 0) return null;

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">ממתינים לאישורך</h2>
      <ul className="space-y-2 text-sm">
        {pendingEnrollments.length > 0 && (
          <li>
            <Link to="/approvals?tab=enrollments" className="flex items-center justify-between hover:text-indigo-600">
              <span>בקשות הצטרפות</span>
              <CountChip n={pendingEnrollments.length} />
            </Link>
          </li>
        )}
        {pendingSwaps.length > 0 && (
          <li>
            <Link to="/swaps" className="flex items-center justify-between hover:text-indigo-600">
              <span>בקשות החלפה</span>
              <CountChip n={pendingSwaps.length} />
            </Link>
          </li>
        )}
        {pendingConstraints > 0 && (
          <li>
            <Link to="/approvals?tab=constraints" className="flex items-center justify-between hover:text-indigo-600">
              <span>בקשות אישי</span>
              <CountChip n={pendingConstraints} />
            </Link>
          </li>
        )}
        {pendingExemptions > 0 && (
          <li>
            <Link to="/approvals?tab=exemptions" className="flex items-center justify-between hover:text-indigo-600">
              <span>בקשות פטור</span>
              <CountChip n={pendingExemptions} />
            </Link>
          </li>
        )}
        {pendingFieldUpdates > 0 && (
          <li>
            <Link to="/approvals?tab=field-updates" className="flex items-center justify-between hover:text-indigo-600">
              <span>עדכוני פרופיל</span>
              <CountChip n={pendingFieldUpdates} />
            </Link>
          </li>
        )}
      </ul>
    </section>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/HomePage.tsx frontend/src/components/dashboard/PendingApprovalsWidget.tsx
git commit -m "feat: pending approvals widget shows all 5 categories"
```

---

### Task 8: Final wiring check

- [ ] **Step 1: Run frontend lint**

```bash
cd frontend && pnpm lint
```
Expected: zero warnings/errors.

- [ ] **Step 2: Smoke test in browser**

Start dev stack (`.\dev.ps1 -NoBot`), open `http://localhost:5173`:
- Holiday background events are visible in the calendar.
- Clicking a duty event opens the modal.
- Hovering a multi-week event highlights both week rows.
- Clicking an upcoming duty row opens the modal; "בקש החלפה" navigates to `/swaps?new=...`.
- Swap widget shows "ההחלפות שלי" title and duty type + date range per row.
- Pending approvals widget shows correct categories with counts.

- [ ] **Step 3: Final commit if any lint fixes were needed**

```bash
git add -p && git commit -m "fix: plan A lint cleanup"
```
