# Nav Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the bottom nav/sidebar into a role-progressive 5–7 tab layout, collapse five planning pages into two tabbed pages, two admin pages into one, move profile to a header icon, and remove ManageSheet.

**Architecture:** Frontend-only. Each existing page gets a named `XContent` export (JSX without `<Layout>`); three new tabbed wrapper pages import these. `UnifiedNav` is rewritten with progressive tabs; submenus use a new generic `NavSheet` component. `Layout` gains profile and gear icons.

**Tech Stack:** React 18, TypeScript, React Router v6, Tailwind CSS, lucide-react, react-i18next, Vitest + React Testing Library.

---

## File Map

| Action | Path |
|--------|------|
| Create | `frontend/src/components/TabBar.tsx` |
| Create | `frontend/src/components/NavSheet.tsx` |
| Create | `frontend/src/pages/planning/AssignmentPage.tsx` |
| Create | `frontend/src/pages/planning/ConfigPage.tsx` |
| Create | `frontend/src/pages/admin/AdminSettingsPage.tsx` |
| Modify | `frontend/src/pages/DutyManagementPage.tsx` |
| Modify | `frontend/src/pages/AlgorithmPage.tsx` |
| Modify | `frontend/src/pages/DutyConfigPage.tsx` |
| Modify | `frontend/src/pages/ShiftsPage.tsx` |
| Modify | `frontend/src/pages/ShiftTemplatesPage.tsx` |
| Modify | `frontend/src/pages/SystemSettingsPage.tsx` |
| Modify | `frontend/src/pages/AdminInviteCodesPage.tsx` |
| Modify | `frontend/src/App.tsx` |
| Modify | `frontend/src/components/UnifiedNav.tsx` |
| Modify | `frontend/src/components/UnifiedNav.test.tsx` |
| Modify | `frontend/src/components/Layout.tsx` |
| Modify | `frontend/src/i18n/he.json` |
| Delete | `frontend/src/components/ManageSheet.tsx` |
| Delete | `frontend/src/components/ManageSheet.test.tsx` |

---

## Task 1: Add i18n keys

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add new nav translation keys**

In `frontend/src/i18n/he.json`, inside the `"nav"` object, add after the existing keys:

```json
"commander": "מפקד",
"planning": "תכנון",
"planning_assignment": "שיבוץ",
"planning_config": "הגדרת תורנויות ומשמרות",
"assignment_manual": "שיבוץ ידני",
"assignment_algorithm": "אלגוריתם",
"config_duty_types": "סוגי תורנויות",
"config_shifts": "משמרות",
"config_templates": "תבניות",
"admin_settings": "הגדרות מערכת",
"admin_invite_codes": "קודי הזמנה"
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "feat(nav): add i18n keys for new nav structure"
```

---

## Task 2: Create TabBar component

**Files:**
- Create: `frontend/src/components/TabBar.tsx`

- [ ] **Step 1: Create `frontend/src/components/TabBar.tsx`**

```tsx
interface TabBarProps {
  tabs: string[];
  active: number;
  onChange: (i: number) => void;
}

export default function TabBar({ tabs, active, onChange }: TabBarProps) {
  return (
    <div className="flex border-b mb-6" dir="rtl">
      {tabs.map((label, i) => (
        <button
          key={i}
          onClick={() => onChange(i)}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
            active === i
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
          data-testid={`tab-${i}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/TabBar.tsx
git commit -m "feat(nav): add TabBar component"
```

---

## Task 3: Create NavSheet component

**Files:**
- Create: `frontend/src/components/NavSheet.tsx`

- [ ] **Step 1: Create `frontend/src/components/NavSheet.tsx`**

```tsx
import { Link } from "react-router-dom";

interface NavSheetItem {
  label: string;
  to: string;
}

interface NavSheetProps {
  open: boolean;
  onClose: () => void;
  items: NavSheetItem[];
  testId?: string;
}

export default function NavSheet({ open, onClose, items, testId }: NavSheetProps) {
  if (!open) return null;

  const linkClass = "block px-4 py-3 rounded hover:bg-gray-100 text-sm font-medium" as const;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
        data-testid={testId ? `${testId}-backdrop` : undefined}
        role="presentation"
      />
      <div
        role="dialog"
        aria-modal="true"
        className="fixed bottom-0 right-0 left-0 md:bottom-0 md:right-24 md:left-auto md:top-0 bg-white z-50 rounded-t-2xl md:rounded-none shadow-xl overflow-y-auto max-h-[50vh] md:max-h-full md:w-48 py-4 space-y-1"
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
        data-testid={testId}
      >
        <div className="flex justify-end px-3">
          <button
            autoFocus
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            aria-label="סגור"
          >
            ✕
          </button>
        </div>
        {items.map((item) => (
          <Link key={item.to} to={item.to} onClick={onClose} className={linkClass}>
            {item.label}
          </Link>
        ))}
      </div>
    </>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/NavSheet.tsx
git commit -m "feat(nav): add NavSheet component for submenus"
```

---

## Task 4: Extract content from planning pages

**Files:**
- Modify: `frontend/src/pages/DutyManagementPage.tsx`
- Modify: `frontend/src/pages/AlgorithmPage.tsx`
- Modify: `frontend/src/pages/DutyConfigPage.tsx`
- Modify: `frontend/src/pages/ShiftsPage.tsx`
- Modify: `frontend/src/pages/ShiftTemplatesPage.tsx`

For each page, add a named export `XContent` for the JSX body (without `<Layout>`), then simplify the default export to `<Layout><XContent /></Layout>`.

- [ ] **Step 1: Extract `DutyManagementContent` from `DutyManagementPage.tsx`**

Open `frontend/src/pages/DutyManagementPage.tsx`. The current default export function contains all the state, handlers, and JSX. Move the entire function body into a new named export, keep the default export as a thin wrapper:

```tsx
// Add this named export (same body as the current default export, minus the <Layout> wrapper):
export function DutyManagementContent() {
  // ... all existing state and handlers unchanged ...
  return (
    <section className="bg-white rounded-lg shadow p-6 space-y-6" data-testid="duty-management-page">
      {/* ... all existing JSX inside <Layout> ... */}
    </section>
  );
}

export default function DutyManagementPage() {
  return (
    <Layout>
      <DutyManagementContent />
    </Layout>
  );
}
```

The `Layout` import stays at the top. All other imports and logic move into `DutyManagementContent`.

- [ ] **Step 2: Extract `AlgorithmContent` from `AlgorithmPage.tsx`**

Same pattern. `AlgorithmPage.tsx` currently has a `Navigate` guard for non-managers — keep this in the default export wrapper:

```tsx
export function AlgorithmContent() {
  // all state/handlers/JSX that was inside <Layout> (excluding Navigate guard)
  // useSearchParams() for jobId stays here — no conflict with tab param
  return (
    <> {/* all existing JSX inside <Layout> */} </>
  );
}

export default function AlgorithmPage() {
  const { user } = useAuth();
  const role = user?.role;
  const canManageDuties = role === "duty_manager" || role === "admin";
  if (!canManageDuties) return <Navigate to="/" replace />;
  return (
    <Layout>
      <AlgorithmContent />
    </Layout>
  );
}
```

- [ ] **Step 3: Extract `DutyConfigContent` from `DutyConfigPage.tsx`**

```tsx
export function DutyConfigContent() {
  // all existing state/handlers/JSX inside <Layout>
  return (
    <section className="bg-white rounded-lg shadow p-6 space-y-8" data-testid="duty-config-page">
      {/* ... */}
    </section>
  );
}

export default function DutyConfigPage() {
  return <Layout><DutyConfigContent /></Layout>;
}
```

- [ ] **Step 4: Extract `ShiftsContent` from `ShiftsPage.tsx`**

```tsx
export function ShiftsContent() {
  // all existing state/handlers/JSX
  return (
    <> {/* existing JSX inside <Layout> */} </>
  );
}

export default function ShiftsPage() {
  return <Layout><ShiftsContent /></Layout>;
}
```

- [ ] **Step 5: Extract `ShiftTemplatesContent` from `ShiftTemplatesPage.tsx`**

```tsx
export function ShiftTemplatesContent() {
  // all existing state/handlers/JSX
  return (
    <section className="bg-white rounded-lg shadow p-6 space-y-4" dir="rtl" data-testid="shift-templates-page">
      {/* ... */}
    </section>
  );
}

export default function ShiftTemplatesPage() {
  return <Layout><ShiftTemplatesContent /></Layout>;
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/DutyManagementPage.tsx frontend/src/pages/AlgorithmPage.tsx frontend/src/pages/DutyConfigPage.tsx frontend/src/pages/ShiftsPage.tsx frontend/src/pages/ShiftTemplatesPage.tsx
git commit -m "refactor(planning): extract Content components from planning pages"
```

---

## Task 5: Extract content from admin pages

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Modify: `frontend/src/pages/AdminInviteCodesPage.tsx`

- [ ] **Step 1: Extract `SystemSettingsContent` from `SystemSettingsPage.tsx`**

```tsx
export function SystemSettingsContent() {
  // all existing state, SETTING_GROUPS constant, handlers, and JSX
  return (
    <section className="bg-white rounded-lg shadow p-6 space-y-6" dir="rtl">
      {/* ... existing JSX inside <Layout> ... */}
    </section>
  );
}

export default function SystemSettingsPage() {
  return <Layout><SystemSettingsContent /></Layout>;
}
```

- [ ] **Step 2: Extract `AdminInviteCodesContent` from `AdminInviteCodesPage.tsx`**

```tsx
export function AdminInviteCodesContent() {
  // all existing state, handlers, and JSX
  return (
    <section className="bg-white rounded-lg shadow p-6 space-y-4" dir="rtl">
      {/* ... existing JSX inside <Layout> ... */}
    </section>
  );
}

export default function AdminInviteCodesPage() {
  return <Layout><AdminInviteCodesContent /></Layout>;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx frontend/src/pages/AdminInviteCodesPage.tsx
git commit -m "refactor(admin): extract Content components from admin pages"
```

---

## Task 6: Create AdminSettingsPage

**Files:**
- Create: `frontend/src/pages/admin/AdminSettingsPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/admin/AdminSettingsPage.tsx`**

```tsx
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import TabBar from "../../components/TabBar";
import { SystemSettingsContent } from "../SystemSettingsPage";
import { AdminInviteCodesContent } from "../AdminInviteCodesPage";

export default function AdminSettingsPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("tab") ?? "0");
  const activeTab = raw >= 0 && raw <= 1 ? raw : 0;
  const setTab = (i: number) => setSearchParams({ tab: String(i) }, { replace: true });

  const tabs = [t("nav.admin_settings"), t("nav.admin_invite_codes")];

  return (
    <Layout>
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} />
      {activeTab === 0 && <SystemSettingsContent />}
      {activeTab === 1 && <AdminInviteCodesContent />}
    </Layout>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/admin/AdminSettingsPage.tsx
git commit -m "feat(admin): add AdminSettingsPage with tabbed system settings + invite codes"
```

---

## Task 7: Create AssignmentPage

**Files:**
- Create: `frontend/src/pages/planning/AssignmentPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/planning/AssignmentPage.tsx`**

```tsx
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import TabBar from "../../components/TabBar";
import { DutyManagementContent } from "../DutyManagementPage";
import { AlgorithmContent } from "../AlgorithmPage";

export default function AssignmentPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("tab") ?? "0");
  const activeTab = raw >= 0 && raw <= 1 ? raw : 0;

  const setTab = (i: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", String(i));
    // clear algorithm-specific params when leaving algorithm tab
    if (i !== 1) next.delete("jobId");
    setSearchParams(next, { replace: true });
  };

  const tabs = [t("nav.assignment_manual"), t("nav.assignment_algorithm")];

  return (
    <Layout>
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} />
      {activeTab === 0 && <DutyManagementContent />}
      {activeTab === 1 && <AlgorithmContent />}
    </Layout>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/planning/AssignmentPage.tsx
git commit -m "feat(planning): add AssignmentPage with שיבוץ ידני + אלגוריתם tabs"
```

---

## Task 8: Create ConfigPage

**Files:**
- Create: `frontend/src/pages/planning/ConfigPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/planning/ConfigPage.tsx`**

```tsx
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import TabBar from "../../components/TabBar";
import { DutyConfigContent } from "../DutyConfigPage";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";

export default function ConfigPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("tab") ?? "0");
  const activeTab = raw >= 0 && raw <= 2 ? raw : 0;
  const setTab = (i: number) => setSearchParams({ tab: String(i) }, { replace: true });

  const tabs = [
    t("nav.config_duty_types"),
    t("nav.config_shifts"),
    t("nav.config_templates"),
  ];

  return (
    <Layout>
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} />
      {activeTab === 0 && <DutyConfigContent />}
      {activeTab === 1 && <ShiftsContent />}
      {activeTab === 2 && <ShiftTemplatesContent />}
    </Layout>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/planning/ConfigPage.tsx
git commit -m "feat(planning): add ConfigPage with duty types + shifts + templates tabs"
```

---

## Task 9: Update App.tsx with new routes and redirects

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update `frontend/src/App.tsx`**

Add imports for the 3 new pages and `Navigate`. Replace the old routes with new routes + redirects:

```tsx
import { Navigate, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import { SoldierModalProvider } from "./contexts/SoldierModalContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import ApprovalsPage from "./pages/ApprovalsPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import DutyConfigPage from "./pages/DutyConfigPage";
import DutyManagementPage from "./pages/DutyManagementPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import MyDutiesPage from "./pages/MyDutiesPage";
import MyRequestsPage from "./pages/MyRequestsPage";
import NotificationsPage from "./pages/NotificationsPage";
import ProfilePage from "./pages/ProfilePage";
import TeamHierarchyPage from "./pages/TeamHierarchyPage";
import ShiftsPage from "./pages/ShiftsPage";
import ShiftTemplatesPage from "./pages/ShiftTemplatesPage";
import SwapsPage from "./pages/SwapsPage";
import TransparencyPage from "./pages/TransparencyPage";
import UnitCalendarPage from "./pages/UnitCalendarPage";
import CommandDashboardPage from "./pages/CommandDashboardPage";
import AlgorithmPage from "./pages/AlgorithmPage";
import RegisterPage from "./pages/RegisterPage";
import TelegramSetupPage from "./pages/TelegramSetupPage";
import AdminInviteCodesPage from "./pages/AdminInviteCodesPage";
import SystemSettingsPage from "./pages/SystemSettingsPage";
import AssignmentPage from "./pages/planning/AssignmentPage";
import ConfigPage from "./pages/planning/ConfigPage";
import AdminSettingsPage from "./pages/admin/AdminSettingsPage";

function ForcedPasswordGate({ children }: { children: ReactElement }) {
  const { mustChangePassword } = useAuth();
  if (mustChangePassword) return <Navigate to="/change-password" replace />;
  return children;
}

function TelegramGate({ children }: { children: ReactElement }) {
  const { telegramRequired, telegramLinked } = useAuth();
  if (telegramRequired && !telegramLinked) return <Navigate to="/setup/telegram" replace />;
  return children;
}

function AppGate({ children }: { children: ReactElement }) {
  return <ForcedPasswordGate><TelegramGate>{children}</TelegramGate></ForcedPasswordGate>;
}

export default function App() {
  return (
    <AuthProvider>
      <SoldierModalProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/change-password" element={<ChangePasswordPage />} />
            <Route path="/setup/telegram" element={<TelegramSetupPage />} />
            <Route path="/" element={<AppGate><HomePage /></AppGate>} />
            <Route path="/team" element={<AppGate><TeamHierarchyPage /></AppGate>} />
            <Route path="/transparency" element={<AppGate><TransparencyPage /></AppGate>} />
            <Route path="/my-duties" element={<AppGate><MyDutiesPage /></AppGate>} />
            <Route path="/my-requests" element={<AppGate><MyRequestsPage /></AppGate>} />
            <Route path="/approvals" element={<AppGate><ApprovalsPage /></AppGate>} />
            <Route path="/unit-calendar" element={<AppGate><UnitCalendarPage /></AppGate>} />
            <Route path="/swaps" element={<AppGate><SwapsPage /></AppGate>} />
            <Route path="/profile" element={<AppGate><ProfilePage /></AppGate>} />
            <Route path="/command-dashboard" element={<AppGate><CommandDashboardPage /></AppGate>} />
            <Route path="/notifications" element={<AppGate><NotificationsPage /></AppGate>} />
            {/* New tabbed planning pages */}
            <Route path="/planning/assignment" element={<AppGate><AssignmentPage /></AppGate>} />
            <Route path="/planning/config" element={<AppGate><ConfigPage /></AppGate>} />
            {/* New admin settings page */}
            <Route path="/admin/settings" element={<AppGate><AdminSettingsPage /></AppGate>} />
            {/* Redirects from old routes */}
            <Route path="/duty-management" element={<Navigate to="/planning/assignment?tab=0" replace />} />
            <Route path="/algorithm" element={<Navigate to="/planning/assignment?tab=1" replace />} />
            <Route path="/duty-config" element={<Navigate to="/planning/config?tab=0" replace />} />
            <Route path="/shifts" element={<Navigate to="/planning/config?tab=1" replace />} />
            <Route path="/shift-templates" element={<Navigate to="/planning/config?tab=2" replace />} />
            <Route path="/admin/system-settings" element={<Navigate to="/admin/settings?tab=0" replace />} />
            <Route path="/admin/invite-codes" element={<Navigate to="/admin/settings?tab=1" replace />} />
            {/* Keep old standalone pages accessible for now (backward compat) */}
            <Route path="/duty-config-old" element={<AppGate><DutyConfigPage /></AppGate>} />
            <Route path="/duty-management-old" element={<AppGate><DutyManagementPage /></AppGate>} />
            <Route path="/shifts-old" element={<AppGate><ShiftsPage /></AppGate>} />
            <Route path="/shift-templates-old" element={<AppGate><ShiftTemplatesPage /></AppGate>} />
            <Route path="/algorithm-old" element={<AppGate><AlgorithmPage /></AppGate>} />
            <Route path="/admin/system-settings-old" element={<AppGate><SystemSettingsPage /></AppGate>} />
            <Route path="/admin/invite-codes-old" element={<AppGate><AdminInviteCodesPage /></AppGate>} />
          </Route>
        </Routes>
      </SoldierModalProvider>
    </AuthProvider>
  );
}
```

Note: the `-old` routes are temporary scaffolding for smoke-testing. They will be removed in Task 12.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(routing): add new planning/admin routes and redirects from old routes"
```

---

## Task 10: Rewrite UnifiedNav and update its tests

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx`
- Modify: `frontend/src/components/UnifiedNav.test.tsx`

- [ ] **Step 1: Write the new `UnifiedNav.test.tsx` first**

Replace the entire content of `frontend/src/components/UnifiedNav.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import UnifiedNav from "./UnifiedNav";

vi.mock("react-router-dom", () => ({
  useLocation: () => ({ pathname: "/" }),
  Link: ({ to, children, className, ...props }: { to: string; children: React.ReactNode; className?: string; [key: string]: unknown }) => (
    <a href={to} className={className} {...props}>{children}</a>
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("../api/constraints", () => ({
  getPendingCount: vi.fn(() => Promise.resolve(0)),
}));
vi.mock("../api/exemptions", () => ({
  getPendingExemptionCount: vi.fn(() => Promise.resolve(0)),
}));
vi.mock("../api/soldiers", () => ({
  getPendingFieldUpdateCount: vi.fn(() => Promise.resolve(0)),
}));

vi.mock("./NavSheet", () => ({
  default: ({ open, testId }: { open: boolean; testId?: string }) =>
    open ? <div data-testid={testId ?? "nav-sheet-open"} /> : null,
}));

describe("UnifiedNav — soldier role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
  });

  test("renders 5 base tabs: my-requests, swaps, home, unit-calendar, transparency", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-my-requests").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-swaps").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-home").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-unit-calendar").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-transparency").length).toBeGreaterThan(0);
  });

  test("does not render commander or planning tabs", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("nav-commander")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-planning")).not.toBeInTheDocument();
  });

  test("does not render profile tab (profile is in header now)", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("nav-profile")).not.toBeInTheDocument();
  });
});

describe("UnifiedNav — commander role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "commander" } });
  });

  test("renders base tabs plus commander tab", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-home").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-commander").length).toBeGreaterThan(0);
  });

  test("does not render planning tab", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("nav-planning")).not.toBeInTheDocument();
  });

  test("commander button opens commander sheet", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("commander-sheet")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByTestId("nav-commander")[0]);
    expect(screen.getByTestId("commander-sheet")).toBeInTheDocument();
  });

  test("shows pending badge on commander tab when approvals pending", async () => {
    const { getPendingCount } = await import("../api/constraints");
    vi.mocked(getPendingCount).mockResolvedValueOnce(3);
    render(<UnifiedNav />);
    await waitFor(() => {
      expect(screen.getByTestId("pending-badge")).toBeInTheDocument();
    });
  });
});

describe("UnifiedNav — duty_manager role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
  });

  test("renders base tabs plus commander and planning tabs", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-commander").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-planning").length).toBeGreaterThan(0);
  });

  test("planning button opens planning sheet", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("planning-sheet")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByTestId("nav-planning")[0]);
    expect(screen.getByTestId("planning-sheet")).toBeInTheDocument();
  });
});

describe("UnifiedNav — admin role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "admin" } });
  });

  test("renders base tabs plus commander and planning tabs", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-commander").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-planning").length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd frontend && npx vitest run src/components/UnifiedNav.test.tsx
```

Expected: multiple FAIL (tests reference testIds that don't exist yet in the old UnifiedNav).

- [ ] **Step 3: Rewrite `frontend/src/components/UnifiedNav.tsx`**

```tsx
import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  House, FileText, ArrowLeftRight, Users, Wrench,
  Calendar, BarChart2,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import NavSheet from "./NavSheet";

interface NavTab {
  label: string;
  icon: React.ReactNode;
  to?: string;
  onClick?: () => void;
  badge?: number;
  testId: string;
}

export default function UnifiedNav() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const location = useLocation();
  const role = user?.role;
  const canApprove = role === "commander" || role === "duty_manager" || role === "admin";
  const canPlan = role === "duty_manager" || role === "admin";

  const [pendingCount, setPendingCount] = useState(0);
  const [commanderSheetOpen, setCommanderSheetOpen] = useState(false);
  const [planningSheetOpen, setPlanningSheetOpen] = useState(false);

  useEffect(() => {
    if (!canApprove) return;
    void (async () => {
      const [c, e, f] = await Promise.all([
        getPendingCount().catch(() => 0),
        getPendingExemptionCount().catch(() => 0),
        getPendingFieldUpdateCount().catch(() => 0),
      ]);
      setPendingCount(c + e + f);
    })();
  }, [canApprove, location.pathname]);

  const baseTabs: NavTab[] = [
    { label: t("nav.my_requests"), icon: <FileText size={20} />, to: "/my-requests", testId: "nav-my-requests" },
    { label: t("nav.swaps"), icon: <ArrowLeftRight size={20} />, to: "/swaps", testId: "nav-swaps" },
    { label: t("nav.home"), icon: <House size={20} />, to: "/", testId: "nav-home" },
    { label: t("nav.unit_calendar"), icon: <Calendar size={20} />, to: "/unit-calendar", testId: "nav-unit-calendar" },
    { label: t("nav.transparency"), icon: <BarChart2 size={20} />, to: "/transparency", testId: "nav-transparency" },
  ];

  const commanderTab: NavTab = {
    label: t("nav.commander"),
    icon: <Users size={20} />,
    onClick: () => setCommanderSheetOpen(true),
    badge: pendingCount,
    testId: "nav-commander",
  };

  const planningTab: NavTab = {
    label: t("nav.planning"),
    icon: <Wrench size={20} />,
    onClick: () => setPlanningSheetOpen(true),
    testId: "nav-planning",
  };

  const tabs: NavTab[] = [
    ...baseTabs,
    ...(canApprove ? [commanderTab] : []),
    ...(canPlan ? [planningTab] : []),
  ];

  const commanderItems = [
    { label: t("nav.team_hierarchy"), to: "/team" },
    { label: t("nav.approvals"), to: "/approvals" },
    { label: t("nav.command_dashboard"), to: "/command-dashboard" },
  ];

  const planningItems = [
    { label: t("nav.planning_assignment"), to: "/planning/assignment" },
    { label: t("nav.planning_config"), to: "/planning/config" },
  ];

  const isActive = (to?: string) => {
    if (!to) return false;
    if (to === "/") return location.pathname === "/";
    return location.pathname.startsWith(to);
  };

  const tabContent = (tab: NavTab, active: boolean) => (
    <>
      {tab.icon}
      {tab.badge != null && tab.badge > 0 && (
        <span
          className="absolute top-1 right-1/4 md:top-2 md:left-3 bg-red-500 text-white text-[10px] rounded-full px-1.5 leading-5"
          data-testid="pending-badge"
        >
          {tab.badge}
        </span>
      )}
      <span className="text-center leading-tight">{tab.label}</span>
    </>
  );

  const mobileTabClass = (active: boolean) =>
    `flex-1 flex flex-col items-center justify-center py-2 min-h-[56px] text-xs gap-1 relative ${
      active ? "text-indigo-600" : "text-gray-400"
    }`;

  const desktopTabClass = (active: boolean) =>
    `relative flex flex-col items-center justify-center py-4 gap-1 text-xs w-full ${
      active ? "text-indigo-600" : "text-gray-400 hover:text-gray-600"
    }`;

  return (
    <>
      <NavSheet
        open={commanderSheetOpen}
        onClose={() => setCommanderSheetOpen(false)}
        items={commanderItems}
        testId="commander-sheet"
      />
      <NavSheet
        open={planningSheetOpen}
        onClose={() => setPlanningSheetOpen(false)}
        items={planningItems}
        testId="planning-sheet"
      />

      {/* Mobile bottom bar */}
      <nav
        aria-label="ניווט ראשי"
        className="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t z-30"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="flex">
          {tabs.map((tab) => {
            const active = isActive(tab.to);
            return tab.to ? (
              <Link
                key={tab.testId}
                to={tab.to}
                className={mobileTabClass(active)}
                data-testid={tab.testId}
              >
                {tabContent(tab, active)}
              </Link>
            ) : (
              <button
                key={tab.testId}
                onClick={tab.onClick}
                className={mobileTabClass(false)}
                data-testid={tab.testId}
              >
                {tabContent(tab, false)}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Desktop sidebar */}
      <nav
        aria-label="ניווט צדדי"
        className="hidden md:flex fixed right-0 top-0 bottom-0 w-24 bg-white border-l flex-col z-30"
        data-testid="sidebar"
      >
        {tabs.map((tab) => {
          const active = isActive(tab.to);
          return tab.to ? (
            <Link
              key={tab.testId}
              to={tab.to}
              className={desktopTabClass(active)}
              data-testid={`desktop-${tab.testId}`}
            >
              {active && (
                <span className="absolute inset-x-2 inset-y-1 bg-indigo-50 rounded-lg -z-10" />
              )}
              {tabContent(tab, active)}
            </Link>
          ) : (
            <button
              key={tab.testId}
              onClick={tab.onClick}
              className={desktopTabClass(false)}
              data-testid={`desktop-${tab.testId}`}
            >
              {tabContent(tab, false)}
            </button>
          );
        })}
      </nav>
    </>
  );
}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd frontend && npx vitest run src/components/UnifiedNav.test.tsx
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/UnifiedNav.tsx frontend/src/components/UnifiedNav.test.tsx
git commit -m "feat(nav): rewrite UnifiedNav with progressive role-based tabs"
```

---

## Task 11: Update Layout.tsx header (profile + gear icons)

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Update `frontend/src/components/Layout.tsx`**

```tsx
import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CircleUser, Settings } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import NotificationBell from "./NotificationBell";
import UnifiedNav from "./UnifiedNav";

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { logout, user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <div className="min-h-screen flex flex-col md:mr-24">
      <UnifiedNav />
      <header className="bg-white shadow-sm border-b">
        <div className="px-4 py-3 flex items-center justify-between">
          {/* Left side: profile icon + optional gear icon */}
          <div className="flex items-center gap-3">
            <Link to="/profile" aria-label={t("nav.profile")} className="text-gray-500 hover:text-indigo-600">
              <CircleUser size={22} />
            </Link>
            {isAdmin && (
              <Link to="/admin/settings" aria-label={t("nav.admin_settings")} className="text-gray-500 hover:text-indigo-600">
                <Settings size={22} />
              </Link>
            )}
          </div>
          {/* Center: app title */}
          <h1 className="text-lg font-bold">{t("app.title")}</h1>
          {/* Right side: notification bell + logout */}
          <div className="flex items-center gap-4">
            <NotificationBell />
            <button
              onClick={() => logout()}
              className="text-sm text-indigo-600 hover:text-indigo-800"
              data-testid="logout-button"
            >
              {t("home.logout")}
            </button>
          </div>
        </div>
      </header>
      <main className="flex-1 px-4 py-6 pb-20 md:pb-6">{children}</main>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "feat(nav): move profile to header icon, add admin gear icon"
```

---

## Task 12: Delete ManageSheet and clean up old routes

**Files:**
- Delete: `frontend/src/components/ManageSheet.tsx`
- Delete: `frontend/src/components/ManageSheet.test.tsx`
- Modify: `frontend/src/App.tsx` (remove temporary `-old` routes and old page imports)

- [ ] **Step 1: Delete ManageSheet files**

```bash
git rm frontend/src/components/ManageSheet.tsx frontend/src/components/ManageSheet.test.tsx
```

- [ ] **Step 2: Remove `-old` scaffold routes and unused page imports from `App.tsx`**

Edit `frontend/src/App.tsx` to remove:
- The 7 `-old` routes added in Task 9
- Imports for `DutyConfigPage`, `DutyManagementPage`, `ShiftsPage`, `ShiftTemplatesPage`, `AlgorithmPage`, `SystemSettingsPage`, `AdminInviteCodesPage` (these pages still exist as files but are no longer directly routed)

The final `App.tsx` imports and routes should only reference: `AssignmentPage`, `ConfigPage`, `AdminSettingsPage` for the planning/admin sections, plus all the unchanged pages.

- [ ] **Step 3: Run all frontend tests**

```bash
cd frontend && npx vitest run
```

Expected: all PASS. If `ManageSheet.test.tsx` is referenced anywhere, fix the import.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(nav): remove ManageSheet and old scaffold routes — nav consolidation complete"
```

---

## Self-Review Checklist

- [x] TabBar component covers AssignmentPage (2 tabs), ConfigPage (3 tabs), AdminSettingsPage (2 tabs)
- [x] URL `?tab=N` param with range clamping in all 3 new pages
- [x] AlgorithmContent's `?jobId` param preserved/handled in AssignmentPage `setTab`
- [x] NavSheet replaces ManageSheet pattern; two instances (commander, planning)
- [x] Pending badge moved from old Approvals tab → new מפקד tab in UnifiedNav
- [x] Profile removed from nav tabs → added to Layout header as icon
- [x] Gear icon in header for admin → `/admin/settings`
- [x] UnitCalendar now accessible to all (route was always open; nav now shows it to all)
- [x] i18n keys added for all new labels
- [x] Redirects cover all 7 old routes
- [x] Tests updated for new tab structure
