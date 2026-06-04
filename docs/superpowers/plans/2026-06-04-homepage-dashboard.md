# Homepage Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder HomePage with a real dashboard: alert banners for expiring mitvahim/alal, a personal duty calendar, an upcoming duties list, active swap status, and a pending-approvals panel for commanders.

**Architecture:** Frontend-only (no new backend endpoints). `HomePage.tsx` fetches all data in parallel via existing API modules and passes it down to five focused widget components in `frontend/src/components/dashboard/`. A shared `dutyTypeColor` utility is extracted from `MyDutiesPage.tsx`. Four new system settings keys control alert thresholds; seed.py gets more realistic swap/enrollment/invite data.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, FullCalendar (`@fullcalendar/react`, `@fullcalendar/daygrid`), react-i18next, react-router-dom.

---

## File Map

| Action | Path |
|--------|------|
| Create | `frontend/src/utils/dutyTypeColor.ts` |
| Modify | `frontend/src/pages/MyDutiesPage.tsx` (import from util) |
| Modify | `frontend/src/pages/SystemSettingsPage.tsx` (add home settings group) |
| Create | `frontend/src/components/dashboard/AlertBanners.tsx` |
| Create | `frontend/src/components/dashboard/DutyCalendarWidget.tsx` |
| Create | `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx` |
| Create | `frontend/src/components/dashboard/SwapStatusWidget.tsx` |
| Create | `frontend/src/components/dashboard/PendingApprovalsWidget.tsx` |
| Modify | `frontend/src/pages/HomePage.tsx` |
| Modify | `backend/app/scripts/seed.py` |

---

## Task 1: Add home settings group to SystemSettingsPage

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`

- [ ] **Step 1: Add the "דף הבית" settings group to `SETTING_GROUPS`**

In `frontend/src/pages/SystemSettingsPage.tsx`, add a new group at the end of the `SETTING_GROUPS` array (after the `"הוגנות אלגוריתם"` group):

```tsx
  {
    label: "דף הבית",
    settings: [
      { key: "home.mitvahim_validity_days", label: "תוקף מיתווחים (ימים)", description: "מספר ימים שמיתווחים בתוקף לאחר ביצוע", type: "number", defaultValue: 180 },
      { key: "home.mitvahim_warn_days", label: "אזהרה לפני פקיעת מיתווחים (ימים)", description: "כמה ימים לפני פקיעת המיתווחים תופיע אזהרה בדף הבית", type: "number", defaultValue: 30 },
      { key: "home.alal_validity_days", label: 'תוקף אל"ל (ימים)', description: 'מספר ימים שאל"ל בתוקף לאחר ביצוע', type: "number", defaultValue: 90 },
      { key: "home.alal_warn_days", label: 'אזהרה לפני פקיעת אל"ל (ימים)', description: 'כמה ימים לפני פקיעת האל"ל תופיע אזהרה בדף הבית', type: "number", defaultValue: 30 },
    ],
  },
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat(home): add home alert settings group to system settings"
```

---

## Task 2: Extract dutyTypeColor utility

**Files:**
- Create: `frontend/src/utils/dutyTypeColor.ts`
- Modify: `frontend/src/pages/MyDutiesPage.tsx`

- [ ] **Step 1: Create `frontend/src/utils/dutyTypeColor.ts`**

```ts
export function dutyTypeColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) & 0xffffffff;
  return `hsl(${Math.abs(h) % 360}, 65%, 55%)`;
}
```

- [ ] **Step 2: Update `MyDutiesPage.tsx` to import from the util**

Remove the local `dutyTypeColor` function definition from `MyDutiesPage.tsx` and add this import at the top:

```tsx
import { dutyTypeColor } from "../utils/dutyTypeColor";
```

- [ ] **Step 3: Verify the app still compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -v "\.test\." | grep -v e2e
```

Expected: same pre-existing errors only (no new ones).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/utils/dutyTypeColor.ts frontend/src/pages/MyDutiesPage.tsx
git commit -m "refactor: extract dutyTypeColor to shared utility"
```

---

## Task 3: Create AlertBanners widget

**Files:**
- Create: `frontend/src/components/dashboard/AlertBanners.tsx`

- [ ] **Step 1: Create `frontend/src/components/dashboard/AlertBanners.tsx`**

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { SettingsMap } from "../../api/systemSettings";

interface Props {
  lastMitvahimDate: string | null;
  lastAlalDate: string | null;
  settings: SettingsMap;
}

function getNum(settings: SettingsMap, key: string, fallback: number): number {
  const v = settings[key];
  return v != null ? Number(v) : fallback;
}

function alertMessage(
  lastDateStr: string | null,
  validityDays: number,
  warnDays: number,
  label: string
): string | null {
  if (!lastDateStr) return `תאריך ${label} לא מעודכן`;
  const expiry = new Date(lastDateStr);
  expiry.setDate(expiry.getDate() + validityDays);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const daysLeft = Math.floor((expiry.getTime() - today.getTime()) / 86_400_000);
  if (daysLeft > warnDays) return null;
  if (daysLeft <= 0) return `${label} פג תוקף`;
  return `${label} פג תוקף בעוד ${daysLeft} ימים (${expiry.toLocaleDateString("he-IL")})`;
}

export default function AlertBanners({ lastMitvahimDate, lastAlalDate, settings }: Props) {
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const mitvahimValidity = getNum(settings, "home.mitvahim_validity_days", 180);
  const mitvahimWarn = getNum(settings, "home.mitvahim_warn_days", 30);
  const alalValidity = getNum(settings, "home.alal_validity_days", 90);
  const alalWarn = getNum(settings, "home.alal_warn_days", 30);

  const alerts: { key: string; message: string }[] = [];

  const mitvMsg = alertMessage(lastMitvahimDate, mitvahimValidity, mitvahimWarn, "מיתווחים");
  if (mitvMsg) alerts.push({ key: "mitvahim", message: mitvMsg });

  const alalMsg = alertMessage(lastAlalDate, alalValidity, alalWarn, 'אל"ל');
  if (alalMsg) alerts.push({ key: "alal", message: alalMsg });

  const visible = alerts.filter((a) => !dismissed.has(a.key));
  if (visible.length === 0) return null;

  return (
    <div className="space-y-2 mb-4" dir="rtl">
      {visible.map((a) => (
        <div
          key={a.key}
          className="flex items-center justify-between bg-amber-50 border border-amber-300 rounded-lg px-4 py-3 cursor-pointer hover:bg-amber-100"
          onClick={() => navigate("/profile")}
          role="alert"
          data-testid={`alert-banner-${a.key}`}
        >
          <span className="text-sm text-amber-800 font-medium">⚠️ {a.message}</span>
          <button
            className="text-amber-500 hover:text-amber-700 text-lg leading-none ml-4"
            onClick={(e) => { e.stopPropagation(); setDismissed((prev) => new Set([...prev, a.key])); }}
            aria-label="סגור"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/dashboard/AlertBanners.tsx
git commit -m "feat(home): add AlertBanners widget"
```

---

## Task 4: Create DutyCalendarWidget

**Files:**
- Create: `frontend/src/components/dashboard/DutyCalendarWidget.tsx`

- [ ] **Step 1: Create `frontend/src/components/dashboard/DutyCalendarWidget.tsx`**

```tsx
import { useMemo } from "react";
import { Link } from "react-router-dom";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import heLocale from "@fullcalendar/core/locales/he";
import { EffectiveDuty } from "../../api/assignments";
import { dutyTypeColor } from "../../utils/dutyTypeColor";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
}

export default function DutyCalendarWidget({ duties, typeNames }: Props) {
  const events = useMemo(() =>
    duties.map((d) => {
      const endDate = new Date(d.end_date);
      endDate.setDate(endDate.getDate() + 1);
      const color = dutyTypeColor(d.duty_type_id);
      return {
        id: d.assignment_id,
        title: typeNames[d.duty_type_id] ?? "תורנות",
        start: d.start_date,
        end: endDate.toISOString().split("T")[0],
        backgroundColor: color,
        borderColor: color,
      };
    }),
  [duties, typeNames]);

  return (
    <section className="bg-white rounded-lg shadow p-4" dir="rtl">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">היומן שלי</h2>
        <Link to="/my-duties" className="text-sm text-indigo-600 hover:text-indigo-800">
          לכל היומן שלי →
        </Link>
      </div>
      <FullCalendar
        plugins={[dayGridPlugin]}
        initialView="dayGridMonth"
        locale={heLocale}
        events={events}
        headerToolbar={{ start: "prev,next", center: "title", end: "" }}
        height="auto"
        editable={false}
        selectable={false}
        eventClick={() => {}}
      />
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/dashboard/DutyCalendarWidget.tsx
git commit -m "feat(home): add DutyCalendarWidget"
```

---

## Task 5: Create UpcomingDutiesWidget

**Files:**
- Create: `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx`

- [ ] **Step 1: Create `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx`**

```tsx
import { Link } from "react-router-dom";
import { EffectiveDuty } from "../../api/assignments";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
}

function formatDateRange(start: string, end: string): string {
  if (start === end) return new Date(start).toLocaleDateString("he-IL");
  return `${new Date(start).toLocaleDateString("he-IL")} – ${new Date(end).toLocaleDateString("he-IL")}`;
}

export default function UpcomingDutiesWidget({ duties, typeNames, locationNames }: Props) {
  const today = new Date().toISOString().split("T")[0];
  const upcoming = duties
    .filter((d) => d.end_date >= today)
    .sort((a, b) => a.start_date.localeCompare(b.start_date))
    .slice(0, 5);

  return (
    <section className="bg-white rounded-lg shadow p-4" dir="rtl">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">תורנויות קרובות</h2>
        <Link to="/my-duties" className="text-sm text-indigo-600 hover:text-indigo-800">
          לכל התורנויות שלי →
        </Link>
      </div>
      {upcoming.length === 0 ? (
        <p className="text-sm text-gray-500">אין תורנויות קרובות</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 border-b">
              <th className="text-right pb-2 font-medium">תאריך</th>
              <th className="text-right pb-2 font-medium">סוג</th>
              <th className="text-right pb-2 font-medium">מיקום</th>
            </tr>
          </thead>
          <tbody>
            {upcoming.map((d) => (
              <tr key={d.assignment_id} className="border-b last:border-0">
                <td className="py-2">{formatDateRange(d.start_date, d.end_date)}</td>
                <td className="py-2">{typeNames[d.duty_type_id] ?? "—"}</td>
                <td className="py-2">{locationNames[d.duty_location_id] ?? "—"}</td>
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
git commit -m "feat(home): add UpcomingDutiesWidget"
```

---

## Task 6: Create SwapStatusWidget

**Files:**
- Create: `frontend/src/components/dashboard/SwapStatusWidget.tsx`

- [ ] **Step 1: Create `frontend/src/components/dashboard/SwapStatusWidget.tsx`**

```tsx
import { Link } from "react-router-dom";
import { SwapRequest } from "../../api/swaps";

interface Props {
  swaps: SwapRequest[];
}

const STATUS_CHIPS: Record<string, string> = {
  open: "bg-amber-100 text-amber-700",
  pending_approval: "bg-blue-100 text-blue-700",
};

const STATUS_LABELS: Record<string, string> = {
  open: "פתוח",
  pending_approval: "ממתין לאישור",
};

export default function SwapStatusWidget({ swaps }: Props) {
  const active = swaps.filter((s) => s.status === "open" || s.status === "pending_approval");

  if (active.length === 0) return null;

  return (
    <section className="bg-white rounded-lg shadow p-4" dir="rtl">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">החלפות שלי</h2>
        <Link to="/swaps" className="text-sm text-indigo-600 hover:text-indigo-800">
          לדף החלפות →
        </Link>
      </div>
      <ul className="space-y-2">
        {active.map((s) => (
          <li key={s.id} className="flex items-center justify-between text-sm border-b last:border-0 pb-2 last:pb-0">
            <span className="text-gray-700">
              {new Date(s.duty_date).toLocaleDateString("he-IL")}
              {s.reason ? ` — ${s.reason}` : ""}
            </span>
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_CHIPS[s.status] ?? "bg-gray-100 text-gray-600"}`}>
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
git commit -m "feat(home): add SwapStatusWidget"
```

---

## Task 7: Create PendingApprovalsWidget

**Files:**
- Create: `frontend/src/components/dashboard/PendingApprovalsWidget.tsx`

- [ ] **Step 1: Create `frontend/src/components/dashboard/PendingApprovalsWidget.tsx`**

```tsx
import { Link } from "react-router-dom";
import { EnrollmentRequestDTO } from "../../api/enrollment";
import { SwapRequest } from "../../api/swaps";

interface Props {
  pendingEnrollments: EnrollmentRequestDTO[];
  pendingSwaps: SwapRequest[];
}

export default function PendingApprovalsWidget({ pendingEnrollments, pendingSwaps }: Props) {
  if (pendingEnrollments.length === 0 && pendingSwaps.length === 0) return null;

  return (
    <section className="bg-white rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">ממתינים לאישורך</h2>
      <ul className="space-y-2 text-sm">
        {pendingEnrollments.length > 0 && (
          <li>
            <Link to="/approvals" className="flex items-center justify-between hover:text-indigo-600">
              <span>בקשות הצטרפות ממתינות</span>
              <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">
                {pendingEnrollments.length}
              </span>
            </Link>
          </li>
        )}
        {pendingSwaps.length > 0 && (
          <li>
            <Link to="/swaps" className="flex items-center justify-between hover:text-indigo-600">
              <span>החלפות הממתינות לאישור</span>
              <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">
                {pendingSwaps.length}
              </span>
            </Link>
          </li>
        )}
      </ul>
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/dashboard/PendingApprovalsWidget.tsx
git commit -m "feat(home): add PendingApprovalsWidget"
```

---

## Task 8: Wire up HomePage

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`

- [ ] **Step 1: Replace `frontend/src/pages/HomePage.tsx` with the full dashboard**

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import AlertBanners from "../components/dashboard/AlertBanners";
import DutyCalendarWidget from "../components/dashboard/DutyCalendarWidget";
import UpcomingDutiesWidget from "../components/dashboard/UpcomingDutiesWidget";
import SwapStatusWidget from "../components/dashboard/SwapStatusWidget";
import PendingApprovalsWidget from "../components/dashboard/PendingApprovalsWidget";

import { useAuth } from "../auth/AuthContext";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { DutyType, DutyLocation, listDutyTypes, listLocations } from "../api/dutyConfig";
import { SwapRequest, listMySwaps, listPendingSwaps } from "../api/swaps";
import { EnrollmentRequestDTO, listPendingEnrollments } from "../api/enrollment";
import { SettingsMap, getSystemSettings } from "../api/systemSettings";

function todayStr(): string {
  return new Date().toISOString().split("T")[0];
}

function offsetDate(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().split("T")[0];
}

export default function HomePage() {
  const { t } = useTranslation();
  const { user } = useAuth();

  const [duties, setDuties] = useState<EffectiveDuty[]>([]);
  const [typeNames, setTypeNames] = useState<Record<string, string>>({});
  const [locationNames, setLocationNames] = useState<Record<string, string>>({});
  const [mySwaps, setMySwaps] = useState<SwapRequest[]>([]);
  const [pendingEnrollments, setPendingEnrollments] = useState<EnrollmentRequestDTO[]>([]);
  const [pendingSwaps, setPendingSwaps] = useState<SwapRequest[]>([]);
  const [settings, setSettings] = useState<SettingsMap>({});

  const canApprove = user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin";

  useEffect(() => {
    if (!user) return;

    const dutyFetch = listEffectiveDuties(user.id, {
      date_from: offsetDate(-30),
      date_to: offsetDate(60),
    }).catch(() => [] as EffectiveDuty[]);

    const typesFetch = listDutyTypes().catch(() => [] as DutyType[]);
    const locsFetch = listLocations().catch(() => [] as DutyLocation[]);
    const swapsFetch = listMySwaps().catch(() => [] as SwapRequest[]);
    const settingsFetch = getSystemSettings().catch(() => ({} as SettingsMap));

    const approvalFetches = canApprove
      ? [
          listPendingEnrollments().catch(() => [] as EnrollmentRequestDTO[]),
          listPendingSwaps().catch(() => [] as SwapRequest[]),
        ]
      : [Promise.resolve([] as EnrollmentRequestDTO[]), Promise.resolve([] as SwapRequest[])];

    void Promise.all([dutyFetch, typesFetch, locsFetch, swapsFetch, settingsFetch, ...approvalFetches]).then(
      ([d, dts, locs, sw, sett, enr, psw]) => {
        setDuties(d as EffectiveDuty[]);
        setTypeNames(Object.fromEntries((dts as DutyType[]).map((t) => [t.id, t.name])));
        setLocationNames(Object.fromEntries((locs as DutyLocation[]).map((l) => [l.id, l.name])));
        setMySwaps(sw as SwapRequest[]);
        setSettings(sett as SettingsMap);
        setPendingEnrollments(enr as EnrollmentRequestDTO[]);
        setPendingSwaps(psw as SwapRequest[]);
      }
    );
  }, [user, canApprove]);

  return (
    <Layout>
      <div className="space-y-4 max-w-3xl mx-auto" dir="rtl">
        <h2 className="text-xl font-semibold">{t("home.welcome", { name: user?.full_name ?? "" })}</h2>

        <AlertBanners
          lastMitvahimDate={user?.last_mitvahim_date ?? null}
          lastAlalDate={user?.last_alal_date ?? null}
          settings={settings}
        />

        <DutyCalendarWidget duties={duties} typeNames={typeNames} />

        <UpcomingDutiesWidget
          duties={duties}
          typeNames={typeNames}
          locationNames={locationNames}
        />

        <SwapStatusWidget swaps={mySwaps} />

        {canApprove && (
          <PendingApprovalsWidget
            pendingEnrollments={pendingEnrollments}
            pendingSwaps={pendingSwaps}
          />
        )}
      </div>
    </Layout>
  );
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -v "\.test\." | grep -v e2e
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/HomePage.tsx
git commit -m "feat(home): wire up homepage dashboard with all widgets"
```

---

## Task 9: Seed enhancements

**Files:**
- Modify: `backend/app/scripts/seed.py`

This task adds more swap requests (10 total, up from 4), 4 unassigned soldiers with enrollment requests, and 1 invite code. All changes are inside `seed()`, gated the same as the existing logic.

- [ ] **Step 1: Add `SoldierEnrollmentRequest` and `RegistrationInviteCode` imports**

At the top of `backend/app/scripts/seed.py`, add to the existing import block from `app.db.models`:

```python
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyReserveLink,
    DutyShift,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionRequest,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    RegistrationInviteCode,
    ScoreAdjustment,
    Soldier,
    SoldierEnrollmentRequest,
    SoldierExemption,
    SoldierFieldUpdate,
    SwapRequest,
)
```

Also add `invite_codes` service import after the existing imports:

```python
from app.services.invite_codes import create_invite_code
```

- [ ] **Step 2: Add invite code seed (not gated)**

After the existing `# ── Score adjustments ─────────────────────────────────────────` block and before the exemption requests block, add:

```python
        # ── Invite code ────────────────────────────────────────────
        if not session.query(RegistrationInviteCode).first():
            create_invite_code(session, uses_left=10, actor_id=s_admin.id)
```

- [ ] **Step 3: Add enrollment requests seed (not gated)**

After the invite code block, add:

```python
        # ── Unassigned soldiers + enrollment requests ───────────────
        unassigned_pns = ["9000001", "9000002", "9000003", "9000004"]
        if not session.query(Soldier).filter(Soldier.personal_number == "9000001").first():
            unassigned = []
            for i, pn in enumerate(unassigned_pns):
                s = Soldier(
                    personal_number=pn,
                    full_name=f"חייל ממתין {i + 1}",
                    password_hash=hashed,
                    role="soldier",
                    hierarchy_node_id=None,
                    enrolled_at=date(2026, 5, 1),
                    must_change_password=False,
                    enlistment_date=date(2025, 6, 1),
                    mandatory_end_date=_mandatory_end(date(2025, 6, 1)),
                    gender="male",
                )
                session.add(s)
                session.flush()
                unassigned.append(s)

            # Find target nodes
            node_mars = next(n for n in all_teams if n.name == "צוות מארס")
            node_mehkar = next(n for n in focus_groups if n.name == "מחקר")
            node_rei = next(n for n in all_teams if n.name == "צוות ריי")
            node_ark = next(n for n in all_teams if n.name == "צוות ארק")

            enrollment_defs = [
                (unassigned[0], node_mars.id, "pending", None),
                (unassigned[1], node_mehkar.id, "pending", None),
                (unassigned[2], node_rei.id, "approved", s_admin.id),
                (unassigned[3], node_ark.id, "rejected", s_admin.id),
            ]
            for soldier, node_id, status, decided_by in enrollment_defs:
                session.add(SoldierEnrollmentRequest(
                    soldier_id=soldier.id,
                    requested_node_id=node_id,
                    status=status,
                    decided_by=decided_by,
                ))
```

- [ ] **Step 4: Expand swap requests to 10 (still inside `if with_assignments:`)**

Find the existing `# ── Swap requests ────────────────────────────────────────────` block inside `if with_assignments:` and replace it with:

```python
            # ── Swap requests ────────────────────────────────────────
            today = date.today()
            future_assignments = [
                a for a in created_assignments if a.start_date >= today - timedelta(days=1)
            ]
            if len(future_assignments) >= 10:
                def _other_soldier(exclude_id):
                    return session.query(Soldier).filter(Soldier.id != exclude_id).first()

                swap_defs = [
                    # (assignment_idx, status, extra_kwargs)
                    (0, "open", {}),
                    (1, "open", {"target_soldier_id": _other_soldier(future_assignments[1].soldier_id).id}),
                    (2, "open", {}),
                    (3, "open", {}),
                    (4, "pending_approval", {"covering_soldier_id": _other_soldier(future_assignments[4].soldier_id).id}),
                    (5, "pending_approval", {"covering_soldier_id": _other_soldier(future_assignments[5].soldier_id).id}),
                    (6, "applied", {
                        "covering_soldier_id": _other_soldier(future_assignments[6].soldier_id).id,
                        "requester_side_approved": True,
                        "covering_side_approved": True,
                    }),
                    (7, "applied", {
                        "covering_soldier_id": _other_soldier(future_assignments[7].soldier_id).id,
                        "requester_side_approved": True,
                        "covering_side_approved": True,
                    }),
                    (8, "rejected", {}),
                    (9, "cancelled", {}),
                ]
                for idx, status, extra in swap_defs:
                    a = future_assignments[idx]
                    session.add(SwapRequest(
                        duty_assignment_id=a.id,
                        duty_date=a.start_date,
                        requesting_soldier_id=a.soldier_id,
                        status=status,
                        reason="בקשת החלפה לצורכי בדיקה",
                        **extra,
                    ))
```

- [ ] **Step 5: Update the printed summary at the end of `seed()`**

Find the line:
```python
        _safe_print(f"  4 swap requests (1 open, 1 open with target, 1 pending approval, 1 applied)")
```

Replace with:
```python
        _safe_print(f"  10 swap requests (4 open, 2 pending approval, 2 applied, 1 rejected, 1 cancelled)")
```

Also add after the existing `_safe_print(f"  15 personal constraints")` line:
```python
        _safe_print(f"  1 invite code")
        _safe_print(f"  4 enrollment requests (2 pending, 1 approved, 1 rejected)")
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/scripts/seed.py
git commit -m "feat(seed): add invite code, enrollment requests, expand swap requests to 10"
```

---

## Self-Review

**Spec coverage check:**

- [x] Alert banners (mitvahim + alal, null + expiry) → Task 3
- [x] Alert banners dismissible, click navigates to ProfilePage → Task 3
- [x] Duty calendar (FullCalendar dayGridMonth, color by type) → Task 4
- [x] Calendar link → MyDutiesPage → Task 4
- [x] Upcoming duties table (next 5, date/type/location) → Task 5
- [x] Upcoming duties link → MyDutiesPage, empty state → Task 5
- [x] My swaps (active only, status chip, hidden if none) → Task 6
- [x] Pending approvals (commander/admin only, hidden if 0) → Task 7
- [x] System settings 4 new keys + settings group → Task 1
- [x] Data fetched in parallel (Promise.all) → Task 8
- [x] Seed: 10 swaps with variety → Task 9
- [x] Seed: 4 enrollment requests + 4 unassigned soldiers → Task 9
- [x] Seed: 1 invite code → Task 9
- [x] dutyTypeColor shared (DutyCalendarWidget uses it) → Task 2
