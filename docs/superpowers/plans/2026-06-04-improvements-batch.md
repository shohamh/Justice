# Improvements Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 13 separate UI/UX issues and add new features: toggle fix, dark mode, mobile zoom, Hebrew typos, help examples, nav badges, duty alerts, ICS download, swaps overhaul, unit calendar swap badges, exemption file uploads, and exemption approver settings.

**Architecture:** FastAPI backend (SQLAlchemy + Alembic), React + Vite + Tailwind CSS frontend (i18next Hebrew). Independent subsystems — tasks can be executed in any order. Tasks 1–6 are quick fixes, Tasks 7–10 are medium, Tasks 11–13 are large features.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL, React 18, TypeScript, Tailwind CSS + tailwindcss-rtl plugin, react-i18next, FullCalendar

---

## Task 1: Fix toggle button RTL direction (Issue 1)

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`

**Problem:** The toggle button sits in a `dir="rtl"` container. Tailwind's `translate-x-6` is a physical (LTR) transform, so the thumb moves the wrong direction visually.

**Fix:** Add `dir="ltr"` to the toggle `<button>` so its internal coordinate system is LTR regardless of parent.

- [ ] **Step 1: Edit SystemSettingsPage.tsx** — add `dir="ltr"` to the boolean toggle button around line 143:

```tsx
{def.type === "boolean" ? (
  <button
    dir="ltr"
    onClick={() => setValue(def.key, !value)}
    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${value ? "bg-indigo-600" : "bg-gray-200"}`}
    aria-pressed={Boolean(value)}
  >
    <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${value ? "translate-x-6" : "translate-x-1"}`} />
  </button>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx
git commit -m "fix: toggle button thumb direction in RTL system settings"
```

---

## Task 2: Fix Hebrew typos — עתודה→רזרבה, יוכפץ→יוקפץ (Issue 6)

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx`
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`

**The typos:**
1. "עתודאים שיוכפצו" → "רזרבות שיוקפצו" (HelpModal.tsx ~line 132)
2. "מכסת עתודה" → "מכסת רזרבה" (HelpModal.tsx ~line 132)
3. "מכפיל עתודה במצב המתנה" → "מכפיל רזרבה במצב המתנה" (SystemSettingsPage.tsx line 44)
4. "חייל עתודה שלא הוקפץ" → "חייל רזרבה שלא הוקפץ" (SystemSettingsPage.tsx line 44)
5. "מכפיל עתודה שהוקפץ" → "מכפיל רזרבה שהוקפץ" (SystemSettingsPage.tsx line 45)
6. "חייל עתודה שהוקפץ לשירות" → "חייל רזרבה שהוקפץ לשירות" (SystemSettingsPage.tsx line 45)
7. "לעתודה" in fairness.reserve_hierarchy_weight description → "לרזרבה" (SystemSettingsPage.tsx line 52-53)
8. "חיילי עתודה" → "חיילי רזרבה" (SystemSettingsPage.tsx line 52)

- [ ] **Step 1: Find all remaining instances of עתודה/עתודאים in source** (exclude i18n keys that are correct):

Run: `grep -rn "עתודה\|עתודאים\|יוכפץ\|יוכפצ" frontend/src --include="*.tsx" --include="*.ts" --include="*.json"`

- [ ] **Step 2: Fix HelpModal.tsx** — line ~132 inside `AlgorithmTab`:

```tsx
{ icon: "🔢", title: "מכסת רזרבה", desc: "האלגוריתם שובץ גם רזרבות שיוקפצו אם הזכאי לא יוכל להגיע." },
```

- [ ] **Step 3: Fix SystemSettingsPage.tsx** — lines 44-53:

```tsx
{ key: "scoring.reserve_standby_multiplier", label: "מכפיל רזרבה במצב המתנה", description: "מכפיל ניקוד לחייל רזרבה שלא הוקפץ", type: "decimal", defaultValue: 0.2 },
{ key: "scoring.reserve_called_up_multiplier", label: "מכפיל רזרבה שהוקפץ", description: "מכפיל ניקוד לחייל רזרבה שהוקפץ לשירות", type: "decimal", defaultValue: 1.0 },
```

Also fix the fairness line:
```tsx
{ key: "fairness.reserve_hierarchy_weight", label: "משקל קרבה היררכית לרזרבה", description: "משקל קרבה היררכית בבחירת חיילי רזרבה (0=ללא משקל, ערכים גבוהים=מעדיפים חיילים קרובים)", type: "decimal", defaultValue: 1.0 },
```

- [ ] **Step 4: Check Python backend for Hebrew strings** (unlikely but verify):

Run: `grep -rn "עתודה\|עתודאים\|יוכפץ" backend/app --include="*.py"`

Fix any found occurrences using the same substitution rules.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HelpModal.tsx frontend/src/pages/SystemSettingsPage.tsx
git commit -m "fix: correct Hebrew reserve terminology (עתודה→רזרבה, יוכפצו→יוקפצו)"
```

---

## Task 3: Dark mode — auto-detect from system preference (Issue 2)

**Files:**
- Modify: `frontend/tailwind.config.cjs`
- Modify: `frontend/src/index.css` (or create if needed)
- Modify: `frontend/src/App.tsx`
- Modify key layout components: `frontend/src/components/Layout.tsx`, `frontend/src/components/UnifiedNav.tsx`, `frontend/src/components/NavSheet.tsx`
- Modify: `frontend/src/pages/LoginPage.tsx`
- Modify main page wrappers: pages with `bg-white rounded-lg shadow` patterns

**Approach:** Use Tailwind's `darkMode: 'media'` — automatically respects `prefers-color-scheme: dark`. Add `dark:` variant classes throughout key structural components.

- [ ] **Step 1: Enable darkMode in tailwind.config.cjs**

```js
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Heebo", "Arial", "sans-serif"],
      },
      colors: {
        approved: "#16a34a",
        pending: "#d97706",
        rejected: "#dc2626",
        cancelled: "#6b7280",
      },
    },
  },
  plugins: [require("tailwindcss-rtl")],
};
```

- [ ] **Step 2: Add dark base styles to index.css** — open `frontend/src/index.css` and add:

```css
@media (prefers-color-scheme: dark) {
  body {
    background-color: #111827; /* gray-900 */
    color: #f9fafb; /* gray-50 */
  }
}
```

- [ ] **Step 3: Find the Layout component** — run `cat frontend/src/components/Layout.tsx` to see the current wrapper. Add `dark:bg-gray-900` to the main wrapper `<div>`.

Typical pattern — if Layout wraps with something like:
```tsx
<div className="min-h-screen bg-gray-100 dark:bg-gray-900 pb-20 md:pb-0 md:pr-24" dir="rtl">
```

- [ ] **Step 4: Update UnifiedNav** — bars need dark backgrounds:
  - Mobile bottom bar: add `dark:bg-gray-800 dark:border-gray-700`
  - Desktop sidebar: add `dark:bg-gray-800 dark:border-gray-700`
  - Tab text: add `dark:text-gray-300` on inactive, `dark:text-indigo-400` on active

- [ ] **Step 5: Update card/section patterns** — most pages use `bg-white rounded-lg shadow`. Replace with `bg-white dark:bg-gray-800`:

Run: `grep -rn "bg-white rounded" frontend/src/pages frontend/src/components --include="*.tsx" -l`

For each file found, add `dark:bg-gray-800` to card wrappers and `dark:text-gray-100` to heading text.

- [ ] **Step 6: Update input/select/textarea elements** — add `dark:bg-gray-700 dark:text-gray-100 dark:border-gray-600` to form inputs.

Run: `grep -rn "border rounded" frontend/src --include="*.tsx" -l`

- [ ] **Step 7: Update LoginPage** — the login form is the entry point, add dark bg.

- [ ] **Step 8: Verify visually** — start the dev server:

Run: `cd frontend && pnpm dev`

Then in browser DevTools > Rendering > Emulate CSS media feature `prefers-color-scheme: dark`. Verify that the major pages (home, nav, system settings, swaps, unit calendar) look correct.

- [ ] **Step 9: Commit**

```bash
git add frontend/tailwind.config.cjs frontend/src/index.css frontend/src/components/ frontend/src/pages/
git commit -m "feat: add dark mode support using prefers-color-scheme media query"
```

---

## Task 4: Mobile pinch-to-zoom — only content area zooms, bars stay fixed (Issue 4)

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/src/components/Layout.tsx` (verify fixed bars)

**Context:** When the user pinch-zooms, browser-native zoom affects the visual viewport. CSS `position: fixed` elements re-render at zoom scale, appearing to "zoom" too. The best practical fix is to ensure the layout uses a scrollable inner content area and the bars are truly `position: fixed` with proper `z-index`. Complete prevention of bar-zooming requires disabling user zoom (bad for a11y) so we instead optimize the experience.

- [ ] **Step 1: Check current viewport meta in index.html**

Run: `cat frontend/index.html`

- [ ] **Step 2: Update viewport meta** — ensure `viewport-fit=cover` is set for proper safe-area handling but do NOT add `user-scalable=no` (bad for accessibility). Change to:

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
```

- [ ] **Step 3: Check Layout.tsx** — open `frontend/src/components/Layout.tsx`. Verify:
  - The main content `<main>` or wrapper div is `overflow-y-auto` so it scrolls independently
  - The bars use `position: fixed` (already done via Tailwind `fixed` class in UnifiedNav)

- [ ] **Step 4: Add Visual Viewport listener** to prevent bars from shifting during zoom on iOS. In `frontend/src/components/UnifiedNav.tsx`, add this effect:

```tsx
useEffect(() => {
  const vv = window.visualViewport;
  if (!vv) return;
  // Force re-layout when visual viewport changes (zoom/pan on iOS)
  const update = () => {
    document.documentElement.style.setProperty("--vvh", `${vv.height}px`);
  };
  vv.addEventListener("resize", update);
  vv.addEventListener("scroll", update);
  update();
  return () => {
    vv.removeEventListener("resize", update);
    vv.removeEventListener("scroll", update);
  };
}, []);
```

And update the mobile bottom nav `style` prop:
```tsx
style={{ paddingBottom: "env(safe-area-inset-bottom)", bottom: 0 }}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/src/components/UnifiedNav.tsx
git commit -m "fix: improve mobile viewport behavior during pinch zoom"
```

---

## Task 5: Add examples to Help Modal (Issue 11)

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx`

**Goal:** Add concrete numerical examples to the Algorithm tab and Fairness tab.

- [ ] **Step 1: Add examples section to AlgorithmTab** — after the existing feature cards, add:

```tsx
<div className="bg-indigo-50 rounded-xl p-4 border border-indigo-200 space-y-3">
  <p className="font-semibold text-indigo-800">📝 דוגמה מספרית</p>
  <p className="text-indigo-700 text-xs leading-relaxed">
    נניח שיש 3 חיילים: דן (ניקוד מנורמל 0.8), יעל (1.0), ורוני (1.4). 
    משמרת חדשה צריכה מישהו עם תג "חוגרים". דן ורוני מתאימים — יעל פטורה.
    האלגוריתם ממיין לפי ניקוד: דן (0.8) ← קודם. 
    אם K=3 (עומק הגרלה), הוא מגריל מתוך שני המועמדים (כאן רק 2): סיכוי 70% לדן, 30% לרוני.
  </p>
  <div className="grid grid-cols-3 gap-2 text-xs text-center">
    <div className="bg-white rounded p-2 border border-indigo-200">
      <p className="font-bold text-indigo-700">דן</p>
      <p>ניקוד: 0.8</p>
      <p className="text-green-600">⬆ עדיפות גבוהה</p>
    </div>
    <div className="bg-white rounded p-2 border border-indigo-200">
      <p className="font-bold text-purple-700">יעל</p>
      <p>ניקוד: 1.0</p>
      <p className="text-gray-500">✗ פטור חל</p>
    </div>
    <div className="bg-white rounded p-2 border border-indigo-200">
      <p className="font-bold text-orange-700">רוני</p>
      <p>ניקוד: 1.4</p>
      <p className="text-orange-600">⬇ עדיפות נמוכה</p>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add examples section to FairnessTab** — after the score-scale cards (~line 210), add:

```tsx
<div className="bg-indigo-50 rounded-xl p-4 border border-indigo-200 space-y-3 mt-4">
  <p className="font-semibold text-indigo-800">📝 דוגמה: חישוב ניקוד מנורמל</p>
  <div className="text-xs space-y-2 text-indigo-700">
    <p>נניח יחידה עם 3 חיילים לאחר 60 יום:</p>
    <div className="overflow-x-auto">
      <table className="w-full text-center border-collapse text-xs">
        <thead>
          <tr className="bg-indigo-100">
            <th className="p-1 border border-indigo-200">חייל</th>
            <th className="p-1 border border-indigo-200">ניקוד מצטבר</th>
            <th className="p-1 border border-indigo-200">ימים פעילים</th>
            <th className="p-1 border border-indigo-200">ניקוד מנורמל</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="p-1 border border-indigo-200">דן</td>
            <td className="p-1 border border-indigo-200">30</td>
            <td className="p-1 border border-indigo-200">60</td>
            <td className="p-1 border border-indigo-200 font-bold text-orange-600">0.75</td>
          </tr>
          <tr className="bg-white">
            <td className="p-1 border border-indigo-200">יעל</td>
            <td className="p-1 border border-indigo-200">40</td>
            <td className="p-1 border border-indigo-200">60</td>
            <td className="p-1 border border-indigo-200 font-bold text-blue-600">1.00</td>
          </tr>
          <tr>
            <td className="p-1 border border-indigo-200">רוני</td>
            <td className="p-1 border border-indigo-200">50</td>
            <td className="p-1 border border-indigo-200">60</td>
            <td className="p-1 border border-indigo-200 font-bold text-green-600">1.25</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p>ממוצע ניקוד: (30+40+50)÷3 = 40. ממוצע ימים: 60. ניקוד מנורמל יעל: (40÷60)÷(40÷60) = <strong>1.00</strong>.</p>
    <p>דן עשה פחות (0.75) → <strong>יקבל תורנות הבאה</strong>. רוני עשה יותר (1.25) → <strong>יחכה</strong>.</p>
  </div>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "feat(help): add concrete numerical examples to algorithm and fairness tabs"
```

---

## Task 6: Add pending-count badge on "אישורי בקשות" inside commander NavSheet (Issue 3)

**Files:**
- Modify: `frontend/src/components/NavSheet.tsx`
- Modify: `frontend/src/components/UnifiedNav.tsx`

**Context:** The commander tab in the nav bar already shows `pendingCount`. But clicking it opens a sheet with items: "אנשי צוות והיררכיה", "אישור בקשות", "דשבורד מפקד". The badge should also appear on the "אישור בקשות" item inside the sheet.

- [ ] **Step 1: Read NavSheet.tsx** — run `cat frontend/src/components/NavSheet.tsx`.

- [ ] **Step 2: Update NavSheet to accept optional badge counts per item**

In `NavSheet.tsx`, change the `items` prop type:

```tsx
interface NavItem {
  label: string;
  to: string;
  badge?: number;
}

interface NavSheetProps {
  open: boolean;
  onClose: () => void;
  items: NavItem[];
  testId: string;
}
```

In the item rendering, add a badge indicator:

```tsx
{items.map((item) => (
  <Link key={item.to} to={item.to} onClick={onClose}
    className="flex items-center justify-between px-4 py-3 text-sm font-medium hover:bg-gray-50 rounded-lg"
  >
    <span>{item.label}</span>
    {item.badge != null && item.badge > 0 && (
      <span className="bg-red-500 text-white text-xs rounded-full px-2 py-0.5 leading-4">
        {item.badge}
      </span>
    )}
  </Link>
))}
```

- [ ] **Step 3: Update UnifiedNav.tsx** — pass `pendingCount` to the approvals item:

```tsx
const commanderItems = [
  { label: t("nav.team_hierarchy"), to: "/team" },
  { label: t("nav.approvals"), to: "/approvals", badge: pendingCount },
  { label: t("nav.command_dashboard"), to: "/command-dashboard" },
];
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/NavSheet.tsx frontend/src/components/UnifiedNav.tsx
git commit -m "feat(nav): show pending-count badge on approvals item in commander sheet"
```

---

## Task 7: Incoming swap requests — בקשות אליי section + nav badge (Issue 7)

**Files:**
- Modify: `backend/app/routes/swaps.py` — add `GET /swaps/incoming/count` endpoint
- Modify: `frontend/src/api/swaps.ts` — add `getIncomingSwapCount()`
- Modify: `frontend/src/pages/SwapsPage.tsx` — add "בקשות אליי" section
- Modify: `frontend/src/components/UnifiedNav.tsx` — add swap badge to swaps nav tab
- Modify: `frontend/src/i18n/he.json` — add translation keys

- [ ] **Step 1: Add backend endpoint — count incoming swap requests**

In `backend/app/routes/swaps.py`, read the existing route structure (run `cat backend/app/routes/swaps.py`), then add:

```python
@router.get("/swaps/incoming/count")
def get_incoming_swap_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    """Count open swap requests where I am the targeted soldier."""
    from sqlalchemy import select, func
    count = session.execute(
        select(func.count())
        .select_from(SwapRequest)
        .where(
            SwapRequest.target_soldier_id == user.id,
            SwapRequest.status == "open",
        )
    ).scalar_one()
    return {"count": count}


@router.get("/swaps/incoming", response_model=list[SwapRequestOut])
def list_incoming_swaps(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapRequestOut]:
    """List open swap requests directed at me."""
    rows = session.execute(
        select(SwapRequest).where(
            SwapRequest.target_soldier_id == user.id,
            SwapRequest.status == "open",
        ).order_by(SwapRequest.created_at.desc())
    ).scalars().all()
    return [_out(r) for r in rows]
```

(Use the same `_out`, `SwapRequestOut`, and imports already in the file.)

- [ ] **Step 2: Run existing backend tests** to confirm nothing broke:

Run: `cd backend && python -m pytest app/routes/tests/ -v`
Expected: all pass

- [ ] **Step 3: Add notification type** — In `backend/app/db/models.py`, `NotificationType` enum already has `swap_offer_incoming`. Verify it's there. If not, add it.

- [ ] **Step 4: Add frontend API functions** — in `frontend/src/api/swaps.ts`, add:

```typescript
export async function getIncomingSwapCount(): Promise<number> {
  const res = await client.get<{ count: number }>("/swaps/incoming/count");
  return res.data.count;
}

export async function listIncomingSwaps(): Promise<SwapRequest[]> {
  const res = await client.get<SwapRequest[]>("/swaps/incoming");
  return res.data;
}
```

- [ ] **Step 5: Add translations to he.json** — in the `"swaps"` section add:

```json
"incoming": "בקשות אליי",
"none_incoming": "אין בקשות החלפה אליך",
"accept_cover": "אני מכסה"
```

- [ ] **Step 6: Add "בקשות אליי" section to SwapsPage.tsx** — add state and section below the existing board section:

```tsx
const [incomingSwaps, setIncomingSwaps] = useState<SwapRequest[]>([]);

// in refresh():
const [mine, board, incoming] = await Promise.all([
  listMySwaps(), listBoard(), listIncomingSwaps()
]);
setMySwaps(mine);
setBoardSwaps(board);
setIncomingSwaps(incoming);
```

Add the UI section at the bottom of the page:

```tsx
{/* Incoming swap requests directed at me */}
<div>
  <h3 className="text-base font-medium mb-2">{t("swaps.incoming")}</h3>
  {incomingSwaps.length === 0 && (
    <p className="text-sm text-gray-500">{t("swaps.none_incoming")}</p>
  )}
  <ul className="space-y-2">
    {incomingSwaps.map(swap => (
      <li key={swap.id} className="border rounded p-3 text-sm space-y-1 border-indigo-200 bg-indigo-50">
        <div className="flex items-center justify-between">
          <span dir="ltr" className="font-medium">{swap.duty_date}</span>
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[swap.status] ?? ""}`}>
            {t(statusKey(swap.status))}
          </span>
        </div>
        {swap.reason && <p className="text-gray-600 text-xs">{swap.reason}</p>}
        <button
          type="button"
          onClick={() => handleClaim(swap.id)}
          className="bg-indigo-600 text-white px-2 py-1 rounded text-xs hover:bg-indigo-700"
        >
          {t("swaps.accept_cover")}
        </button>
      </li>
    ))}
  </ul>
</div>
```

- [ ] **Step 7: Add swap badge to nav** — in `frontend/src/components/UnifiedNav.tsx`, add incoming swap count to the swaps nav item:

```tsx
const [pendingCount, setPendingCount] = useState(0);
const [swapIncomingCount, setSwapIncomingCount] = useState(0);

// add to the existing useEffect that fetches pendingCount:
const swapCount = await getIncomingSwapCount().catch(() => 0);
setSwapIncomingCount(swapCount);
```

Import `getIncomingSwapCount` from `"../api/swaps"`.

Update the baseTabs swaps entry:
```tsx
{ label: t("nav.swaps"), icon: <ArrowLeftRight size={20} />, to: "/swaps", badge: swapIncomingCount, testId: "nav-swaps" },
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/routes/swaps.py frontend/src/api/swaps.ts frontend/src/pages/SwapsPage.tsx frontend/src/components/UnifiedNav.tsx frontend/src/i18n/he.json
git commit -m "feat(swaps): add incoming swap requests section and nav badge"
```

---

## Task 8: Upcoming duty alerts — configurable days ahead setting (Issue 8)

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx` — add setting definition
- Modify: `frontend/src/components/dashboard/AlertBanners.tsx` — add upcoming duty alerts
- Modify: `frontend/src/i18n/he.json` — add translation keys
- Modify: `frontend/src/api/systemSettings.ts` — already handles generic settings

**Context:** The system already has `AlertBanners.tsx` in the dashboard. We need to add duty-near-alert using `listEffectiveDuties` (from `api/assignments.ts`) filtered to duties within N days (from system setting `alerts.upcoming_duty_days`).

- [ ] **Step 1: Add system setting definition** in `frontend/src/pages/SystemSettingsPage.tsx`:

In `SETTING_GROUPS`, add a new "התראות" group before the closing bracket:

```tsx
{
  label: "התראות",
  settings: [
    {
      key: "alerts.upcoming_duty_days",
      label: "ימי הקדמה להתראת תורנות",
      description: "כמה ימים לפני תורנות תוצג התראה (0 = ללא התראה)",
      type: "number",
      defaultValue: 3,
    },
  ],
},
```

- [ ] **Step 2: Add translations to he.json** — add to the `"home"` section (or top-level):

```json
"upcoming_duty_alert": {
  "today": "היום",
  "tomorrow": "מחר",
  "day_after": "מחרתיים",
  "in_days": "בעוד {{count}} ימים",
  "title": "תורנות קרובה",
  "dismiss": "הבנתי"
}
```

- [ ] **Step 3: Create alert logic in AlertBanners.tsx** (or add to homepage dashboard). Read the current file first:

Run: `cat frontend/src/components/dashboard/AlertBanners.tsx`

Add a new section for upcoming duties. The key utility function:

```tsx
function daysUntil(dateStr: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(dateStr);
  target.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86400000);
}

function formatDaysUntil(days: number, t: (key: string, opts?: object) => string): string {
  if (days === 0) return t("upcoming_duty_alert.today");
  if (days === 1) return t("upcoming_duty_alert.tomorrow");
  if (days === 2) return t("upcoming_duty_alert.day_after");
  return t("upcoming_duty_alert.in_days", { count: days });
}
```

In the AlertBanners component, fetch upcoming duties and the system setting:

```tsx
const [upcomingAlerts, setUpcomingAlerts] = useState<{ duty: EffectiveDuty; days: number }[]>([]);

useEffect(() => {
  (async () => {
    const [duties, settings] = await Promise.all([
      listEffectiveDuties(user.id).catch(() => [] as EffectiveDuty[]),
      getSystemSettings().catch(() => ({} as SettingsMap)),
    ]);
    const alertDays = Number(settings["alerts.upcoming_duty_days"] ?? 3);
    if (alertDays === 0) return;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const alerts = duties
      .map(d => ({ duty: d, days: daysUntil(d.start_date) }))
      .filter(({ days }) => days >= 0 && days <= alertDays)
      .sort((a, b) => a.days - b.days);
    setUpcomingAlerts(alerts);
  })();
}, [user]);
```

Render the alerts:

```tsx
{upcomingAlerts.map(({ duty, days }) => (
  <div key={duty.assignment_id}
    className="flex items-start gap-3 bg-amber-50 border border-amber-300 rounded-lg p-3 text-sm"
    dir="rtl"
  >
    <span className="text-xl">⏰</span>
    <div className="flex-1">
      <p className="font-semibold text-amber-800">
        {t("upcoming_duty_alert.title")} — {formatDaysUntil(days, t)}
      </p>
      <p className="text-amber-700">
        {types[duty.duty_type_id] ?? duty.duty_type_id} · {locs[duty.duty_location_id] ?? ""} · {dayOfWeekHe(duty.start_date)} {duty.start_date}
      </p>
    </div>
  </div>
))}
```

Where `dayOfWeekHe` formats a date string as Hebrew day name:

```tsx
function dayOfWeekHe(dateStr: string): string {
  const days = ["ראשון","שני","שלישי","רביעי","חמישי","שישי","שבת"];
  return "יום " + days[new Date(dateStr).getDay()];
}
```

- [ ] **Step 4: Import needed types** — `EffectiveDuty` from `"../../api/assignments"`, `getSystemSettings`, `SettingsMap` from `"../../api/systemSettings"`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx frontend/src/components/dashboard/AlertBanners.tsx frontend/src/i18n/he.json
git commit -m "feat: configurable upcoming duty alert banner (system setting alerts.upcoming_duty_days)"
```

---

## Task 9: ICS calendar invitation download for duties (Issue 9)

**Files:**
- Create: `frontend/src/utils/icsCalendar.ts`
- Modify: `frontend/src/pages/MyDutiesPage.tsx`
- Modify: `frontend/src/i18n/he.json`

**Approach:** Generate an `.ics` (iCalendar) file client-side and trigger a browser download. No backend changes needed — all data is already available on the frontend.

- [ ] **Step 1: Create ICS utility**

Create `frontend/src/utils/icsCalendar.ts`:

```typescript
import type { EffectiveDuty } from "../api/assignments";

function formatICSDate(dateStr: string): string {
  // dateStr is "YYYY-MM-DD", output is "YYYYMMDD"
  return dateStr.replace(/-/g, "");
}

function escapeICS(str: string): string {
  return str.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
}

export function downloadDutyICS(
  duty: EffectiveDuty,
  dutyTypeName: string,
  locationName: string,
): void {
  const uid = `duty-${duty.assignment_id}@callofduty`;
  const dtstart = formatICSDate(duty.start_date);
  // ICS all-day events: DTEND is exclusive (day after)
  const endDate = new Date(duty.end_date);
  endDate.setDate(endDate.getDate() + 1);
  const dtend = endDate.toISOString().slice(0, 10).replace(/-/g, "");
  const summary = escapeICS(`תורנות: ${dutyTypeName}`);
  const location = escapeICS(locationName);
  const now = new Date().toISOString().replace(/[-:.]/g, "").slice(0, 15) + "Z";

  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//CallOfDuty//HE",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${uid}`,
    `DTSTAMP:${now}`,
    `DTSTART;VALUE=DATE:${dtstart}`,
    `DTEND;VALUE=DATE:${dtend}`,
    `SUMMARY:${summary}`,
    `LOCATION:${location}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");

  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `תורנות-${duty.start_date}.ics`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 2: Write a unit test for the ICS utility**

Create `frontend/src/utils/icsCalendar.test.ts`:

```typescript
import { describe, it, expect, vi, afterEach } from "vitest";

// We can't easily test the DOM manipulation, but we can test the ICS string generation
// by extracting it. For now test the date helpers via integration.

describe("ICS date formatting", () => {
  it("formats YYYY-MM-DD to YYYYMMDD", () => {
    // Import internal logic through the downloadDutyICS output by intercepting URL.createObjectURL
    const blobData: string[] = [];
    const origBlob = global.Blob;
    global.Blob = class MockBlob {
      constructor(parts: string[]) { blobData.push(...parts); }
    } as unknown as typeof Blob;
    
    const { downloadDutyICS } = await import("./icsCalendar");
    // mock document
    const a = { href: "", download: "", click: vi.fn() };
    vi.spyOn(document, "createElement").mockReturnValue(a as unknown as HTMLElement);
    vi.spyOn(document.body, "appendChild").mockImplementation(() => null as unknown as Node);
    vi.spyOn(document.body, "removeChild").mockImplementation(() => null as unknown as Node);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    
    downloadDutyICS(
      { assignment_id: "test-id", duty_type_id: "dt1", duty_location_id: "loc1", start_date: "2026-06-10", end_date: "2026-06-10", is_reserve: false },
      "שמירה",
      "מחנה"
    );
    
    expect(blobData[0]).toContain("DTSTART;VALUE=DATE:20260610");
    expect(blobData[0]).toContain("SUMMARY:תורנות: שמירה");
    
    global.Blob = origBlob;
  });
});
```

- [ ] **Step 3: Run test**

Run: `cd frontend && pnpm test --run src/utils/icsCalendar.test.ts`
Expected: PASS (adjust test if needed based on test runner setup)

- [ ] **Step 4: Add translation keys to he.json**:

```json
"my_duties": {
  ...existing...,
  "add_to_calendar": "הוסף ליומן",
  "download_ics": "הורד אירוע (.ics)"
}
```

- [ ] **Step 5: Add download button to MyDutiesPage.tsx**

In the duty detail section or in the calendar event popup, add a button. First read the current click handler `handleEventClick` — it sets `selectedDuty`. In the detail display (find the section that renders `selectedDuty`), add:

```tsx
{selectedDuty && (
  <div className="mt-2">
    <button
      type="button"
      onClick={() => downloadDutyICS(selectedDuty, types[selectedDuty.duty_type_id] ?? "", locs[selectedDuty.duty_location_id] ?? "")}
      className="text-xs text-indigo-600 hover:underline flex items-center gap-1"
    >
      📅 {t("my_duties.add_to_calendar")}
    </button>
  </div>
)}
```

Import `downloadDutyICS` from `"../utils/icsCalendar"`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/utils/icsCalendar.ts frontend/src/utils/icsCalendar.test.ts frontend/src/pages/MyDutiesPage.tsx frontend/src/i18n/he.json
git commit -m "feat: ICS calendar download button for individual duties"
```

---

## Task 10: Unit calendar — swap request badges per shift (Issue 10)

**Files:**
- Modify: `backend/app/routes/swaps.py` — add `GET /swaps/shift-counts` endpoint
- Modify: `backend/app/routes/calendar.py` — include swap counts in CalendarShift response
- Modify: `frontend/src/api/calendar.ts` — update `CalendarShift` type to include `swap_request_count`
- Modify: `frontend/src/components/UnitCalendar.tsx` — show badge on events with swap count
- Modify: `frontend/src/components/ShiftDetailPanel.tsx` — add "accept for free" swap action
- Modify: `frontend/src/i18n/he.json` — translation keys

- [ ] **Step 1: Add swap count to calendar shifts** 

In `backend/app/routes/calendar.py`, read the current `CalendarShift` schema and the query. Add a `swap_request_count` field:

First read the file: `cat backend/app/routes/calendar.py`

In the `CalendarShiftOut` schema, add:
```python
swap_request_count: int = 0
```

In the query that builds shifts, add a subquery to count open swap requests per shift date range:

```python
from sqlalchemy import func, select
from app.db.models import SwapRequest, DutyAssignment

# For each shift, count open swap requests overlapping its date range
# A swap request is for a specific duty_assignment on a specific duty_date
# We count requests where the assignment belongs to this shift

def _swap_count_for_shift(session: Session, shift_id: uuid.UUID) -> int:
    return session.execute(
        select(func.count())
        .select_from(SwapRequest)
        .join(DutyAssignment, DutyAssignment.id == SwapRequest.duty_assignment_id)
        .where(
            DutyAssignment.duty_shift_id == shift_id,
            SwapRequest.status == "open",
        )
    ).scalar_one()
```

When building each `CalendarShiftOut`, populate `swap_request_count`:
```python
swap_request_count=_swap_count_for_shift(session, shift.id),
```

- [ ] **Step 2: Update frontend CalendarShift type** in `frontend/src/api/calendar.ts`:

Add to the interface:
```typescript
swap_request_count?: number;
```

- [ ] **Step 3: Show badge on FullCalendar events** in `frontend/src/components/UnitCalendar.tsx`

In the `events` useMemo, add `extendedProps.swapCount`:
```tsx
extendedProps: { shiftId: s.id, dutyTypeId: s.duty_type_id, swapCount: s.swap_request_count ?? 0 },
```

Add a `eventContent` render prop to FullCalendar:
```tsx
eventContent={(arg) => {
  const count = arg.event.extendedProps.swapCount as number;
  return (
    <div className="flex items-center gap-1 w-full px-1 text-xs overflow-hidden">
      <span className="truncate flex-1">{arg.event.title}</span>
      {count > 0 && (
        <span className="bg-orange-500 text-white rounded-full px-1 text-[10px] leading-4 flex-shrink-0">
          {count}
        </span>
      )}
    </div>
  );
}}
```

- [ ] **Step 4: Add "accept for free" in ShiftDetailPanel**

Read: `cat frontend/src/components/ShiftDetailPanel.tsx`

In the section that lists primary/reserve soldiers, for each primary/reserve assignment, add a button "החלף אותי" (if the current user is NOT this soldier). Clicking it calls `claimSwap` if there's an open swap request, otherwise shows a modal to offer replacement.

Add these translations to he.json in `unit_calendar`:
```json
"swap_requests_count": "{{count}} בקשות החלפה",
"cover_for_free": "כסה בחינם",
"offer_swap": "הצע החלפה"
```

For the "cover for free" action — check if there's an open SwapRequest for this assignment. If yes, call `claimSwap(swapId)`. If no open request, show a message explaining how to initiate.

Add to `frontend/src/api/swaps.ts`:
```typescript
export async function listSwapsForAssignment(assignmentId: string): Promise<SwapRequest[]> {
  const res = await client.get<SwapRequest[]>(`/swaps/for-assignment/${assignmentId}`);
  return res.data;
}
```

Add the backend endpoint in `backend/app/routes/swaps.py`:
```python
@router.get("/swaps/for-assignment/{assignment_id}", response_model=list[SwapRequestOut])
def list_swaps_for_assignment(
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapRequestOut]:
    rows = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == assignment_id,
            SwapRequest.status == "open",
        )
    ).scalars().all()
    return [_out(r) for r in rows]
```

- [ ] **Step 5: Run backend tests**

Run: `cd backend && python -m pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/swaps.py backend/app/routes/calendar.py frontend/src/api/calendar.ts frontend/src/api/swaps.ts frontend/src/components/UnitCalendar.tsx frontend/src/components/ShiftDetailPanel.tsx frontend/src/i18n/he.json
git commit -m "feat(calendar): swap request count badges on shifts + cover action in detail panel"
```

---

## Task 11: Swaps page major overhaul (Issue 5)

**Files:**
- Modify: `frontend/src/pages/SwapsPage.tsx` — full rewrite
- Modify: `frontend/src/api/swaps.ts` — new API functions
- Modify: `backend/app/routes/swaps.py` — new endpoints
- Modify: `frontend/src/i18n/he.json` — new translation keys

**New UX:** The page has 3 tabs:
1. **הבקשות שלי** — list my duties, click "בקש החלפה" per duty
2. **לוח פתוח** — existing open board
3. **בקשות אליי** — incoming requests (moved from Task 7)

**"בקש החלפה" flow:**
- Opens a modal showing the selected duty
- Radio: "פרסם בלוח הפתוח" or "שלח לאנשים ספציפיים" or "שלח לתת-היררכיה"
- Optional personal message (for empathy in open board)
- Submit → creates SwapRequest

**"הצע החלפה" (when covering someone):**
- Either "כסה בחינם (מוסיף לניקוד שלך)" or "הצע שיבוץ בתמורה"
- If offering in return: show list of my duties → select one or more
- Submit → creates covering offer with offered duty IDs

**Backend changes needed:**
- Add `offered_assignment_ids` JSONB field to `swap_requests` table (for duties offered in trade)
- New migration `0038_swap_offered_assignments.py`
- Update `_out` to include this field

- [ ] **Step 1: Create Alembic migration**

Create `backend/alembic/versions/0038_swap_offered_assignments.py`:

```python
"""add offered_assignment_ids to swap_requests

Revision ID: 0038
Revises: 0037
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "swap_requests",
        sa.Column(
            "offered_assignment_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("swap_requests", "offered_assignment_ids")
```

- [ ] **Step 2: Update SwapRequest model** in `backend/app/db/models.py` — add field after `decision_note`:

```python
offered_assignment_ids: Mapped[list[Any]] = mapped_column(
    JSONB, server_default=text("'[]'::jsonb"), default_factory=list
)
```

- [ ] **Step 3: Run migration**

Run: `cd backend && alembic upgrade head`
Expected: Applied 0038

- [ ] **Step 4: Update backend routes** in `backend/app/routes/swaps.py`

Update `SwapRequestOut` to include `offered_assignment_ids`:
```python
offered_assignment_ids: list[str] = []
```

Update `_out` function:
```python
offered_assignment_ids=[str(x) for x in (r.offered_assignment_ids or [])],
```

Add `POST /swaps/{id}/offer` endpoint for submitting a covering offer with optional duty trade:

```python
class CoverOfferInput(BaseModel):
    offered_assignment_ids: list[uuid.UUID] = []

@router.post("/swaps/{swap_id}/offer", response_model=SwapRequestOut)
def submit_cover_offer(
    swap_id: uuid.UUID,
    body: CoverOfferInput,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapRequestOut:
    swap = session.get(SwapRequest, swap_id)
    if swap is None:
        raise HTTPException(status_code=404, detail="swap_not_found")
    if swap.status != "open":
        raise HTTPException(status_code=400, detail="swap_not_open")
    if swap.requesting_soldier_id == user.id:
        raise HTTPException(status_code=400, detail="cannot_cover_own_swap")
    swap.covering_soldier_id = user.id
    swap.offered_assignment_ids = [str(aid) for aid in body.offered_assignment_ids]
    swap.status = "pending_approval"
    session.commit()
    return _out(swap)
```

Add `POST /swaps` endpoint accepting `target_node_ids` (list of hierarchy node IDs for sub-hierarchy targeting):

The existing `CreateSwapInput` in swaps.py already exists; add `target_node_ids: list[uuid.UUID] = []` field:
```python
class CreateSwapInput(BaseModel):
    duty_assignment_id: uuid.UUID
    duty_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str | None = None
    target_soldier_id: uuid.UUID | None = None
    target_node_ids: list[uuid.UUID] = []
```

(The existing create endpoint will now accept this — targeting a node is stored as a notification/broadcast but the SwapRequest itself remains targeting `None` or a specific soldier. For node targeting, the backend creates one SwapRequest per soldier in those nodes or a single open request — for simplicity, create a single open SwapRequest and notify the subhierarchy soldiers.)

- [ ] **Step 5: Update frontend API** in `frontend/src/api/swaps.ts`

Add `offered_assignment_ids` to `SwapRequest` type:
```typescript
offered_assignment_ids: string[];
```

Add new functions:
```typescript
export async function submitCoverOffer(
  swapId: string,
  offeredAssignmentIds: string[] = [],
): Promise<SwapRequest> {
  const res = await client.post<SwapRequest>(`/swaps/${swapId}/offer`, {
    offered_assignment_ids: offeredAssignmentIds,
  });
  return res.data;
}
```

- [ ] **Step 6: Add translations to he.json** in the `"swaps"` section:

```json
"tab_mine": "הבקשות שלי",
"tab_board": "לוח פתוח",
"tab_incoming": "בקשות אליי",
"ask_swap": "בקש החלפה",
"post_open": "פרסם בלוח הפתוח",
"send_to_soldier": "שלח לחייל ספציפי",
"send_to_subhierarchy": "שלח לתת-יחידה",
"personal_message": "הודעה אישית (לעורר אמפתיה...)",
"cover_free": "כסה בחינם (מוסיף לניקוד שלך)",
"offer_trade": "הצע שיבוץ בתמורה",
"select_duties_to_offer": "בחר תורנויות להציע בתמורה",
"submit_offer": "שלח הצעה",
"no_duties": "אין תורנויות להצגה",
"my_upcoming_duties": "התורנויות שלי"
```

- [ ] **Step 7: Rewrite SwapsPage.tsx**

Replace the existing component with a tabbed layout:

```tsx
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import TabBar from "../components/TabBar";
import { useAuth } from "../auth/AuthContext";
import {
  SwapRequest, cancelSwap, claimSwap, createSwap, listBoard,
  listMySwaps, listIncomingSwaps, submitCoverOffer,
  CreateSwapInput,
} from "../api/swaps";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { listDutyTypes, DutyType } from "../api/dutyConfig";

const STATUS_COLORS: Record<string, string> = {
  applied: "bg-green-100 text-green-700",
  pending_approval: "bg-amber-100 text-amber-700",
  open: "bg-amber-100 text-amber-700",
  rejected: "bg-red-100 text-red-700",
  cancelled: "bg-gray-100 text-gray-600",
};

function statusKey(status: string) {
  const map: Record<string, string> = {
    open: "swaps.status_open",
    pending_approval: "swaps.status_pending_approval",
    applied: "swaps.status_applied",
    rejected: "swaps.status_rejected",
    cancelled: "swaps.status_cancelled",
  };
  return map[status] ?? status;
}

// Modal for requesting a swap for a specific duty
function AskSwapModal({
  duty,
  dutyTypeName,
  onClose,
  onCreated,
}: {
  duty: EffectiveDuty;
  dutyTypeName: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"open" | "soldier">("open");
  const [targetSoldierId, setTargetSoldierId] = useState("");
  const [reason, setReason] = useState("");
  const [dutyDate, setDutyDate] = useState(duty.start_date);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const input: CreateSwapInput = {
        duty_assignment_id: duty.assignment_id,
        duty_date: dutyDate,
        reason: reason || null,
        target_soldier_id: mode === "soldier" && targetSoldierId ? targetSoldierId : null,
      };
      await createSwap(input);
      onCreated();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{t("swaps.ask_swap")}: {dutyTypeName}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="text-sm text-gray-600">
            <span>{t("swaps.duty_date")}: </span>
            <input type="date" value={dutyDate} onChange={e => setDutyDate(e.target.value)}
              min={duty.start_date} max={duty.end_date}
              className="border rounded px-1 py-0.5 text-xs" required />
          </div>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" name="mode" checked={mode === "open"} onChange={() => setMode("open")} />
              {t("swaps.post_open")}
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" name="mode" checked={mode === "soldier"} onChange={() => setMode("soldier")} />
              {t("swaps.send_to_soldier")}
            </label>
          </div>
          {mode === "soldier" && (
            <input
              type="text"
              placeholder="מספר אישי של חייל"
              value={targetSoldierId}
              onChange={e => setTargetSoldierId(e.target.value)}
              className="w-full border rounded px-2 py-1 text-sm"
            />
          )}
          <textarea
            placeholder={t("swaps.personal_message")}
            value={reason}
            onChange={e => setReason(e.target.value)}
            rows={3}
            className="w-full border rounded px-2 py-1 text-sm"
          />
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded">{t("swaps.cancel")}</button>
            <button type="submit" className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">{t("swaps.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Modal for offering to cover a swap (free or with trade)
function CoverOfferModal({
  swap,
  myDuties,
  dutyTypes,
  onClose,
  onDone,
}: {
  swap: SwapRequest;
  myDuties: EffectiveDuty[];
  dutyTypes: Record<string, string>;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"free" | "trade">("free");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  function toggleDuty(id: string) {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }

  async function handleSubmit() {
    setError(null);
    try {
      await submitCoverOffer(swap.id, mode === "trade" ? selectedIds : []);
      onDone();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{t("swaps.offer_trade")}</h3>
          <button onClick={onClose} className="text-gray-500">✕</button>
        </div>
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="radio" name="cover_mode" checked={mode === "free"} onChange={() => setMode("free")} />
            {t("swaps.cover_free")}
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="radio" name="cover_mode" checked={mode === "trade"} onChange={() => setMode("trade")} />
            {t("swaps.offer_trade")}
          </label>
          {mode === "trade" && (
            <div className="space-y-1 max-h-40 overflow-y-auto border rounded p-2">
              <p className="text-xs text-gray-500 mb-1">{t("swaps.select_duties_to_offer")}:</p>
              {myDuties.filter(d => d.assignment_id !== swap.duty_assignment_id).map(d => (
                <label key={d.assignment_id} className="flex items-center gap-2 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(d.assignment_id)}
                    onChange={() => toggleDuty(d.assignment_id)}
                  />
                  <span>{dutyTypes[d.duty_type_id] ?? d.duty_type_id} — {d.start_date}</span>
                </label>
              ))}
            </div>
          )}
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded">{t("swaps.cancel")}</button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={mode === "trade" && selectedIds.length === 0}
              className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
            >
              {t("swaps.submit_offer")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function SwapsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [tab, setTab] = useState(0);
  const [myDuties, setMyDuties] = useState<EffectiveDuty[]>([]);
  const [dutyTypes, setDutyTypes] = useState<Record<string, string>>({});
  const [mySwaps, setMySwaps] = useState<SwapRequest[]>([]);
  const [boardSwaps, setBoardSwaps] = useState<SwapRequest[]>([]);
  const [incomingSwaps, setIncomingSwaps] = useState<SwapRequest[]>([]);
  const [askSwapDuty, setAskSwapDuty] = useState<EffectiveDuty | null>(null);
  const [coverSwap, setCoverSwap] = useState<SwapRequest | null>(null);

  const refresh = useCallback(async () => {
    if (!user) return;
    const [mine, board, incoming, duties, dts] = await Promise.all([
      listMySwaps(),
      listBoard(),
      listIncomingSwaps(),
      listEffectiveDuties(user.id).catch(() => [] as EffectiveDuty[]),
      (await import("../api/dutyConfig")).listDutyTypes().catch(() => [] as DutyType[]),
    ]);
    setMySwaps(mine);
    setBoardSwaps(board);
    setIncomingSwaps(incoming);
    setMyDuties(duties);
    setDutyTypes(Object.fromEntries(dts.map(d => [d.id, d.name])));
  }, [user]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function handleCancel(id: string) {
    try { await cancelSwap(id); await refresh(); }
    catch (err: unknown) {
      alert((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "שגיאה");
    }
  }

  async function handleClaim(id: string) {
    try { await claimSwap(id); await refresh(); }
    catch (err: unknown) {
      alert((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "שגיאה");
    }
  }

  const tabs = [t("swaps.tab_mine"), t("swaps.tab_board"), t("swaps.tab_incoming")];

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6" dir="rtl" data-testid="swaps-page">
        <h2 className="text-xl font-semibold mb-4">{t("swaps.title")}</h2>
        <TabBar tabs={tabs} active={tab} onChange={setTab} />

        {/* Tab 0: My upcoming duties — request swap */}
        {tab === 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-gray-600">{t("swaps.my_upcoming_duties")}</h3>
            {myDuties.length === 0 && <p className="text-sm text-gray-500">{t("swaps.no_duties")}</p>}
            <ul className="space-y-2">
              {myDuties.map(d => (
                <li key={d.assignment_id} className="border rounded p-3 text-sm flex items-center justify-between">
                  <div>
                    <span className="font-medium">{dutyTypes[d.duty_type_id] ?? d.duty_type_id}</span>
                    <span className="text-gray-500 mr-2 text-xs" dir="ltr">{d.start_date} → {d.end_date}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setAskSwapDuty(d)}
                    className="text-xs bg-indigo-600 text-white px-2 py-1 rounded hover:bg-indigo-700"
                  >
                    {t("swaps.ask_swap")}
                  </button>
                </li>
              ))}
            </ul>
            {mySwaps.length > 0 && (
              <div className="mt-4 border-t pt-4">
                <h3 className="text-sm font-medium text-gray-600 mb-2">{t("swaps.mine")}</h3>
                <ul className="space-y-2">
                  {mySwaps.map(swap => (
                    <li key={swap.id} className="border rounded p-3 text-sm space-y-1">
                      <div className="flex items-center justify-between">
                        <span dir="ltr" className="font-medium">{swap.duty_date}</span>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[swap.status] ?? ""}`}>
                          {t(statusKey(swap.status))}
                        </span>
                      </div>
                      {swap.reason && <p className="text-gray-500 text-xs">{swap.reason}</p>}
                      {(swap.status === "open" || swap.status === "pending_approval") && (
                        <button type="button" onClick={() => handleCancel(swap.id)} className="text-red-600 text-xs hover:underline">
                          {t("swaps.cancel")}
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Tab 1: Open board */}
        {tab === 1 && (
          <div className="space-y-2">
            {boardSwaps.length === 0 && <p className="text-sm text-gray-500">{t("swaps.none_board")}</p>}
            <ul className="space-y-2">
              {boardSwaps.map(swap => (
                <li key={swap.id} className="border rounded p-3 text-sm space-y-1">
                  <div className="flex items-center justify-between">
                    <span dir="ltr" className="font-medium">{swap.duty_date}</span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[swap.status] ?? ""}`}>
                      {t(statusKey(swap.status))}
                    </span>
                  </div>
                  {swap.reason && <p className="text-gray-600 text-xs">{swap.reason}</p>}
                  <button
                    type="button"
                    onClick={() => setCoverSwap(swap)}
                    className="bg-indigo-600 text-white px-2 py-1 rounded text-xs hover:bg-indigo-700"
                  >
                    {t("swaps.cover")}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Tab 2: Incoming swap requests */}
        {tab === 2 && (
          <div className="space-y-2">
            {incomingSwaps.length === 0 && <p className="text-sm text-gray-500">{t("swaps.none_incoming")}</p>}
            <ul className="space-y-2">
              {incomingSwaps.map(swap => (
                <li key={swap.id} className="border border-indigo-200 bg-indigo-50 rounded p-3 text-sm space-y-1">
                  <div className="flex items-center justify-between">
                    <span dir="ltr" className="font-medium">{swap.duty_date}</span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[swap.status] ?? ""}`}>
                      {t(statusKey(swap.status))}
                    </span>
                  </div>
                  {swap.reason && <p className="text-gray-600 text-xs">{swap.reason}</p>}
                  <button
                    type="button"
                    onClick={() => setCoverSwap(swap)}
                    className="bg-indigo-600 text-white px-2 py-1 rounded text-xs hover:bg-indigo-700"
                  >
                    {t("swaps.cover")}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {askSwapDuty && (
        <AskSwapModal
          duty={askSwapDuty}
          dutyTypeName={dutyTypes[askSwapDuty.duty_type_id] ?? askSwapDuty.duty_type_id}
          onClose={() => setAskSwapDuty(null)}
          onCreated={async () => { setAskSwapDuty(null); await refresh(); }}
        />
      )}

      {coverSwap && (
        <CoverOfferModal
          swap={coverSwap}
          myDuties={myDuties}
          dutyTypes={dutyTypes}
          onClose={() => setCoverSwap(null)}
          onDone={async () => { setCoverSwap(null); await refresh(); }}
        />
      )}
    </Layout>
  );
}
```

- [ ] **Step 8: Run frontend type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No type errors (fix any that appear)

- [ ] **Step 9: Commit**

```bash
git add backend/alembic/versions/0038_swap_offered_assignments.py backend/app/db/models.py backend/app/routes/swaps.py frontend/src/pages/SwapsPage.tsx frontend/src/api/swaps.ts frontend/src/i18n/he.json
git commit -m "feat(swaps): major page overhaul - duty list, cover offer modal, trade offer flow"
```

---

## Task 12: Exemption request file upload for medical exemptions (Issue 12)

**Files:**
- Modify: `backend/app/db/models.py` — add `is_medical` to `ExemptionType`, add `ExemptionRequestFile` model
- Create: `backend/alembic/versions/0039_exemption_request_files.py`
- Modify: `backend/app/routes/exemption_requests.py` — file upload/download endpoints
- Modify: `backend/app/routes/duty_config.py` — expose `is_medical` in exemption type CRUD
- Modify: `frontend/src/api/exemptions.ts` — add file upload/download functions
- Modify: `frontend/src/pages/MyRequestsPage.tsx` — conditional file upload input
- Modify: `frontend/src/pages/ApprovalsPage.tsx` — show attachments for commander review
- Modify: `frontend/src/i18n/he.json` — translation keys

- [ ] **Step 1: Create migration**

Create `backend/alembic/versions/0039_exemption_request_files.py`:

```python
"""add exemption request files and is_medical to exemption_types

Revision ID: 0039
Revises: 0038
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exemption_types",
        sa.Column(
            "is_medical",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_table(
        "exemption_request_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("exemption_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["exemption_request_id"], ["exemption_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["soldiers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("exemption_request_files")
    op.drop_column("exemption_types", "is_medical")
```

- [ ] **Step 2: Update models** in `backend/app/db/models.py`

Add `is_medical` to `ExemptionType` (after `is_global`):
```python
is_medical: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
```

Add new `ExemptionRequestFile` class after `ExemptionRequest`:
```python
class ExemptionRequestFile(Base):
    __tablename__ = "exemption_request_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    exemption_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exemption_requests.id", ondelete="CASCADE")
    )
    file_name: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(sa.LargeBinary)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 3: Run migration**

Run: `cd backend && alembic upgrade head`
Expected: Applied 0039

- [ ] **Step 4: Add file endpoints** in `backend/app/routes/exemption_requests.py`

```python
from fastapi import File, UploadFile, Response
from app.db.models import ExemptionRequestFile, ExemptionType

class ExemptionFileOut(BaseModel):
    id: uuid.UUID
    file_name: str
    content_type: str
    created_at: str


@router.post(
    "/me/exemption-requests/{request_id}/files",
    response_model=ExemptionFileOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_exemption_file(
    request_id: uuid.UUID,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionFileOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None or req.soldier_id != user.id:
        raise HTTPException(status_code=404, detail="exemption_request_not_found")
    # Validate file type
    allowed_types = {"application/pdf", "image/jpeg", "image/png", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="invalid_file_type")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:  # 10 MB max
        raise HTTPException(status_code=400, detail="file_too_large")
    ef = ExemptionRequestFile(
        exemption_request_id=request_id,
        file_name=file.filename or "file",
        content_type=file.content_type,
        data=data,
        uploaded_by=user.id,
    )
    session.add(ef)
    session.commit()
    return ExemptionFileOut(
        id=ef.id,
        file_name=ef.file_name,
        content_type=ef.content_type,
        created_at=ef.created_at.isoformat(),
    )


@router.get("/exemption-requests/{request_id}/files", response_model=list[ExemptionFileOut])
def list_exemption_files(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionFileOut]:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="exemption_request_not_found")
    # Only the requester or an approver can view files
    if req.soldier_id != user.id:
        root_ids = scope_root_ids(session, user)
        if not root_ids:
            raise HTTPException(status_code=403, detail="no_permission")
    files = session.execute(
        select(ExemptionRequestFile)
        .where(ExemptionRequestFile.exemption_request_id == request_id)
        .order_by(ExemptionRequestFile.created_at)
    ).scalars().all()
    return [
        ExemptionFileOut(id=f.id, file_name=f.file_name, content_type=f.content_type, created_at=f.created_at.isoformat())
        for f in files
    ]


@router.get("/exemption-requests/{request_id}/files/{file_id}")
def download_exemption_file(
    request_id: uuid.UUID,
    file_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> Response:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="exemption_request_not_found")
    if req.soldier_id != user.id:
        root_ids = scope_root_ids(session, user)
        if not root_ids:
            raise HTTPException(status_code=403, detail="no_permission")
    ef = session.get(ExemptionRequestFile, file_id)
    if ef is None or ef.exemption_request_id != request_id:
        raise HTTPException(status_code=404, detail="file_not_found")
    return Response(
        content=ef.data,
        media_type=ef.content_type,
        headers={"Content-Disposition": f'attachment; filename="{ef.file_name}"'},
    )
```

- [ ] **Step 5: Update ExemptionTypeOut** in `backend/app/routes/duty_config.py` — read the file first, then add `is_medical: bool` to the schema and to the `_out` function.

- [ ] **Step 6: Run backend tests**

Run: `cd backend && python -m pytest -v`
Expected: PASS

- [ ] **Step 7: Add frontend API functions** in `frontend/src/api/exemptions.ts`:

```typescript
export interface ExemptionFile {
  id: string;
  file_name: string;
  content_type: string;
  created_at: string;
}

export async function uploadExemptionFile(requestId: string, file: File): Promise<ExemptionFile> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await client.post<ExemptionFile>(`/me/exemption-requests/${requestId}/files`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

export async function listExemptionFiles(requestId: string): Promise<ExemptionFile[]> {
  const res = await client.get<ExemptionFile[]>(`/exemption-requests/${requestId}/files`);
  return res.data;
}

export function exemptionFileDownloadUrl(requestId: string, fileId: string): string {
  return `/api/exemption-requests/${requestId}/files/${fileId}`;
}
```

- [ ] **Step 8: Update ExemptionType interface** in `frontend/src/api/dutyConfig.ts` — add `is_medical?: boolean` to the `ExemptionType` interface.

- [ ] **Step 9: Update MyRequestsPage.tsx** — add file upload section

After submitting an exemption request, if the exemption type is medical, show a file upload prompt. Since the current flow creates the request first and then uploads, we need to:
1. Track `lastCreatedRequestId` state
2. After successful submission, if `isMedical`, show a file upload section

```tsx
const [lastCreatedRequestId, setLastCreatedRequestId] = useState<string | null>(null);
const [uploadFiles, setUploadFiles] = useState<File[]>([]);
const [uploadError, setUploadError] = useState<string | null>(null);

// In onErSubmit, after successful creation:
const createdReq = await submitExemptionRequest({ ... });
const selectedType = exemptionTypes.find(et => et.id === erTypeId);
if (selectedType?.is_medical) {
  setLastCreatedRequestId(createdReq.id);
} else {
  setErTypeId(""); setErStart(""); setErEnd(""); setErReason("");
  await refresh();
}
```

Add a file upload section that appears when `lastCreatedRequestId` is set:

```tsx
{lastCreatedRequestId && (
  <div className="mt-3 p-3 border border-blue-200 bg-blue-50 rounded space-y-2" dir="rtl">
    <p className="text-sm font-medium text-blue-800">{t("exemption_requests.upload_required")}</p>
    <p className="text-xs text-blue-600">{t("exemption_requests.upload_hint")}</p>
    <input
      type="file"
      multiple
      accept=".pdf,image/*"
      onChange={e => setUploadFiles(Array.from(e.target.files ?? []))}
      className="text-xs"
    />
    {uploadError && <p className="text-red-500 text-xs">{uploadError}</p>}
    <div className="flex gap-2">
      <button
        type="button"
        onClick={async () => {
          setUploadError(null);
          try {
            for (const f of uploadFiles) {
              await uploadExemptionFile(lastCreatedRequestId, f);
            }
            setLastCreatedRequestId(null);
            setUploadFiles([]);
            setErTypeId(""); setErStart(""); setErEnd(""); setErReason("");
            await refresh();
          } catch {
            setUploadError("שגיאה בהעלאת הקובץ");
          }
        }}
        disabled={uploadFiles.length === 0}
        className="px-3 py-1 text-sm bg-blue-600 text-white rounded disabled:opacity-50"
      >
        {t("exemption_requests.upload_send")}
      </button>
      <button
        type="button"
        onClick={() => { setLastCreatedRequestId(null); setUploadFiles([]); void refresh(); }}
        className="px-3 py-1 text-sm border rounded"
      >
        {t("exemption_requests.upload_skip")}
      </button>
    </div>
  </div>
)}
```

Import `uploadExemptionFile` from `"../api/exemptions"`.

- [ ] **Step 10: Update ApprovalsPage** — show attached files in exemption request review

Read: `cat frontend/src/pages/ApprovalsPage.tsx`

In the exemption request detail view, after the request metadata, add:

```tsx
// Fetch files for each pending exemption request
const [requestFiles, setRequestFiles] = useState<Record<string, ExemptionFile[]>>({});

useEffect(() => {
  for (const req of exemptionRequests) {
    listExemptionFiles(req.id)
      .then(files => setRequestFiles(prev => ({ ...prev, [req.id]: files })))
      .catch(() => {});
  }
}, [exemptionRequests]);
```

In the exemption request row, show file links:
```tsx
{(requestFiles[req.id] ?? []).map(f => (
  <a
    key={f.id}
    href={exemptionFileDownloadUrl(req.id, f.id)}
    target="_blank"
    rel="noreferrer"
    className="text-blue-600 text-xs hover:underline flex items-center gap-1"
  >
    📎 {f.file_name}
  </a>
))}
```

- [ ] **Step 11: Add translations to he.json** in the `"exemption_requests"` section:

```json
"upload_required": "נדרש העלאת מסמך רפואי",
"upload_hint": "אנא צרף קובץ PDF או תמונה של האישור הרפואי",
"upload_send": "העלה ושלח",
"upload_skip": "דלג (העלה מאוחר יותר)",
"files": "מסמכים מצורפים"
```

- [ ] **Step 12: Update ExemptionType in duty config UI** — in `frontend/src/pages/DutyConfigPage.tsx`, add a checkbox for `is_medical` in the exemption type form.

Read the file first: `cat frontend/src/pages/DutyConfigPage.tsx`

Add `is_medical` checkbox to the exemption type create/edit form.

- [ ] **Step 13: Commit**

```bash
git add backend/alembic/versions/0039_exemption_request_files.py backend/app/db/models.py backend/app/routes/exemption_requests.py backend/app/routes/duty_config.py frontend/src/api/exemptions.ts frontend/src/api/dutyConfig.ts frontend/src/pages/MyRequestsPage.tsx frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/DutyConfigPage.tsx frontend/src/i18n/he.json
git commit -m "feat(exemptions): file upload for medical exemption requests, viewer for commanders"
```

---

## Task 13: Configurable exemption approver setting (Issue 13)

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx` — add setting definition
- Modify: `backend/app/routes/exemption_requests.py` — check setting before approval
- Modify: `backend/app/services/settings_loader.py` — add helper
- Modify: `frontend/src/i18n/he.json` — translation

**New system setting:** `exemptions.approver` — values: `"duty_manager"` (default, current behaviour) or `"commander_rasn"` (only commanders with rank >= רסן can approve).

Note: The current authorization uses `Action.CONSTRAINT_APPROVE` in `authz.py`. We need to check the system setting and conditionally enforce rank requirement.

- [ ] **Step 1: Add the setting definition to SystemSettingsPage.tsx**

In `SETTING_GROUPS`, add to a new "פטורים" group (or add to the existing "אילוצים אישיים" group):

```tsx
{
  label: "פטורים",
  settings: [
    {
      key: "exemptions.require_rasn_approver",
      label: "מאשר פטורים — דרג רסן ומעלה בלבד",
      description: "אם מסומן, רק מפקדים בדרג רסן ומעלה יוכלו לאשר פטורים (בנוסף למנהלי תורניות)",
      type: "boolean",
      defaultValue: false,
    },
  ],
},
```

- [ ] **Step 2: Add setting helper** in `backend/app/services/settings_loader.py` — read the file first:

Run: `cat backend/app/services/settings_loader.py`

Add a helper function to fetch the approver requirement:

```python
def exemptions_require_rasn(session: Session) -> bool:
    """Returns True if only commanders of rank >= רסן may approve exemptions."""
    from app.db.models import SystemSetting
    row = session.get(SystemSetting, "exemptions.require_rasn_approver")
    if row is None:
        return False
    return bool(row.value)
```

- [ ] **Step 3: Enforce setting in approval route**

In `backend/app/routes/exemption_requests.py`, in the `approve_exemption_request` function, add the rank check after the existing `authorize` call:

```python
from app.services.settings_loader import exemptions_require_rasn

# In approve_exemption_request, after authorize():
if exemptions_require_rasn(session):
    RASN_AND_ABOVE = {"רסן", "סגן אלוף", "אלוף משנה", "אלוף", "תת אלוף"}
    if user.role not in ("duty_manager", "admin") and user.rank not in RASN_AND_ABOVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient_rank_for_exemption_approval",
        )
```

Do the same in `reject_exemption_request`.

- [ ] **Step 4: Add error translation to he.json**:

```json
"errors": {
  ...existing...,
  "insufficient_rank_for_exemption_approval": "נדרש דרג רסן ומעלה לאישור פטורים"
}
```

- [ ] **Step 5: Run backend tests**

Run: `cd backend && python -m pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx backend/app/services/settings_loader.py backend/app/routes/exemption_requests.py frontend/src/i18n/he.json
git commit -m "feat(exemptions): system setting to require commander rank >= רסן for exemption approval"
```

---

## Self-Review: Spec Coverage

| Issue | Task | Coverage |
|-------|------|----------|
| 1. Toggle button weird | Task 1 | ✅ `dir="ltr"` fix |
| 2. Dark mode auto | Task 3 | ✅ Tailwind `darkMode: 'media'` |
| 3. Badge on אישורי בקשות | Task 6 | ✅ NavSheet badge per item |
| 4. Mobile pinch zoom bars | Task 4 | ✅ Visual viewport + fixed positioning |
| 5. Swaps page overhaul | Task 11 | ✅ Tabbed UI, ask-swap modal, cover-offer modal, trade duties |
| 6. Hebrew typos | Task 2 | ✅ עתודה→רזרבה, יוכפצו→יוקפצו |
| 7. בקשות אליי + badge | Task 7 | ✅ Section + nav badge |
| 8. Duty alerts configurable | Task 8 | ✅ System setting + alert banners |
| 9. Calendar invite (.ics) | Task 9 | ✅ ICS download utility + button |
| 10. Calendar swap badges | Task 10 | ✅ Shift event badges + accept action |
| 11. Help modal examples | Task 5 | ✅ Numerical examples in both tabs |
| 12. Exemption file upload | Task 12 | ✅ DB model + upload endpoint + frontend |
| 13. Exemption approver setting | Task 13 | ✅ System setting + rank check |

**Note on placeholder scan:** Tasks 3 (dark mode) and 10 (unit calendar) require reading existing file content before editing — both have "read the file first" steps to prevent placeholder issues. All code blocks contain actual implementation code.

**Type consistency check:**
- `ExemptionRequestFile` model name consistent across migration, model, route
- `ExemptionFile` TypeScript type consistent across `api/exemptions.ts` and page usages
- `SwapRequest.offered_assignment_ids: string[]` consistent in model, route, frontend type
- `downloadDutyICS` function name consistent in utility and import
