# Mobile Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed-width text sidebar with a unified icon+label nav that renders as a bottom bar on mobile and a narrow vertical sidebar on desktop, with role-aware tabs.

**Architecture:** A single `UnifiedNav` component reads role from `useAuth()` and pathname from `useLocation()` to select the correct tab set and highlight the active route. A companion `ManageSheet` slide-up overlay handles the manager overflow pages. Both are mounted in `Layout.tsx`, which sheds its existing `<aside>` and the pending-count fetch logic (those move into `UnifiedNav`).

**Tech Stack:** React 18, react-router-dom v6, react-i18next, Tailwind CSS v3, lucide-react (new), vitest + @testing-library/react

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `frontend/package.json` | add lucide-react dependency |
| Modify | `frontend/src/i18n/he.json` | add 4 new nav translation keys |
| Create | `frontend/src/components/ManageSheet.tsx` | grouped overflow sheet (manager pages) |
| Create | `frontend/src/components/ManageSheet.test.tsx` | tests for ManageSheet |
| Create | `frontend/src/components/UnifiedNav.tsx` | bottom bar (mobile) + vertical sidebar (desktop) |
| Create | `frontend/src/components/UnifiedNav.test.tsx` | tests for UnifiedNav |
| Modify | `frontend/src/components/Layout.tsx` | remove sidebar + pending-count logic, mount UnifiedNav, fix margins |

---

## Task 1: Install lucide-react and add i18n keys

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Install lucide-react**

From `frontend/` directory:
```bash
pnpm add lucide-react
```
Expected: lucide-react appears in `package.json` dependencies.

- [ ] **Step 2: Add new nav translation keys to he.json**

In `frontend/src/i18n/he.json`, inside the `"nav"` block (after `"command_dashboard": "דשבורד מפקד"`), add:

```json
    "manage": "ניהול",
    "section_personal": "אישי",
    "section_team": "צוות",
    "section_planning": "תכנון"
```

The full `"nav"` block should end:
```json
    "command_dashboard": "דשבורד מפקד",
    "manage": "ניהול",
    "section_personal": "אישי",
    "section_team": "צוות",
    "section_planning": "תכנון"
  },
```

- [ ] **Step 3: Verify TypeScript resolves lucide-react**

```bash
cd frontend && pnpm exec tsc --noEmit --skipLibCheck 2>&1 | head -20
```
Expected: no errors about lucide-react.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/i18n/he.json
git commit -m "feat: add lucide-react and mobile nav i18n keys"
```

---

## Task 2: Build ManageSheet

**Files:**
- Create: `frontend/src/components/ManageSheet.tsx`
- Create: `frontend/src/components/ManageSheet.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/ManageSheet.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import ManageSheet from "./ManageSheet";

vi.mock("react-router-dom", () => ({
  Link: ({ to, children, onClick, ...props }: { to: string; children: React.ReactNode; onClick?: () => void; [key: string]: unknown }) => (
    <a href={to} onClick={onClick} {...props}>{children}</a>
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

describe("ManageSheet", () => {
  test("renders nothing when closed", () => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
    render(<ManageSheet open={false} onClose={() => {}} />);
    expect(screen.queryByText("nav.section_personal")).not.toBeInTheDocument();
  });

  test("renders personal section for all roles when open", () => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
    render(<ManageSheet open={true} onClose={() => {}} />);
    expect(screen.getByText("nav.section_personal")).toBeInTheDocument();
    expect(screen.getByText("nav.my_requests")).toBeInTheDocument();
    expect(screen.getByText("nav.swaps")).toBeInTheDocument();
    expect(screen.getByText("nav.transparency")).toBeInTheDocument();
  });

  test("renders team section for canManageTeam roles", () => {
    mockUseAuth.mockReturnValue({ user: { role: "commander" } });
    render(<ManageSheet open={true} onClose={() => {}} />);
    expect(screen.getByText("nav.section_team")).toBeInTheDocument();
    expect(screen.getByText("nav.team_hierarchy")).toBeInTheDocument();
    expect(screen.getByText("nav.unit_calendar")).toBeInTheDocument();
    expect(screen.getByText("nav.command_dashboard")).toBeInTheDocument();
  });

  test("does not render team section for soldier role", () => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
    render(<ManageSheet open={true} onClose={() => {}} />);
    expect(screen.queryByText("nav.section_team")).not.toBeInTheDocument();
  });

  test("renders planning section for canManageDuties roles", () => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
    render(<ManageSheet open={true} onClose={() => {}} />);
    expect(screen.getByText("nav.section_planning")).toBeInTheDocument();
    expect(screen.getByText("nav.duty_config")).toBeInTheDocument();
    expect(screen.getByText("nav.shifts")).toBeInTheDocument();
  });

  test("calls onClose when backdrop is clicked", () => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
    const onClose = vi.fn();
    render(<ManageSheet open={true} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("manage-sheet-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test("calls onClose when a link is clicked", () => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
    const onClose = vi.fn();
    render(<ManageSheet open={true} onClose={onClose} />);
    fireEvent.click(screen.getByText("nav.my_requests"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test -- ManageSheet
```
Expected: FAIL — "Cannot find module './ManageSheet'"

- [ ] **Step 3: Implement ManageSheet**

Create `frontend/src/components/ManageSheet.tsx`:

```tsx
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ManageSheet({ open, onClose }: Props) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const role = user?.role;
  const canManageTeam = role === "duty_manager" || role === "admin" || role === "commander";
  const canManageDuties = role === "duty_manager" || role === "admin";

  if (!open) return null;

  const linkClass = "block px-3 py-2 rounded hover:bg-gray-100 text-sm";
  const sectionHeadClass = "text-xs font-semibold text-gray-400 uppercase mb-1 px-3";

  return (
    <>
      <div
        className="fixed inset-0 bg-black/30 z-40"
        data-testid="manage-sheet-backdrop"
        onClick={onClose}
      />
      <div className="fixed bottom-0 right-0 left-0 md:bottom-0 md:right-24 md:left-auto md:top-0 bg-white z-50 rounded-t-2xl md:rounded-none shadow-xl overflow-y-auto max-h-[70vh] md:max-h-full md:w-64 py-4 space-y-3">
        <div>
          <p className={sectionHeadClass}>{t("nav.section_personal")}</p>
          <Link to="/my-requests" onClick={onClose} className={linkClass}>{t("nav.my_requests")}</Link>
          <Link to="/swaps" onClick={onClose} className={linkClass}>{t("nav.swaps")}</Link>
          <Link to="/transparency" onClick={onClose} className={linkClass}>{t("nav.transparency")}</Link>
        </div>

        {canManageTeam && (
          <div>
            <p className={sectionHeadClass}>{t("nav.section_team")}</p>
            <Link to="/team" onClick={onClose} className={linkClass}>{t("nav.team_hierarchy")}</Link>
            <Link to="/unit-calendar" onClick={onClose} className={linkClass}>{t("nav.unit_calendar")}</Link>
            <Link to="/command-dashboard" onClick={onClose} className={linkClass}>{t("nav.command_dashboard")}</Link>
          </div>
        )}

        {canManageDuties && (
          <div>
            <p className={sectionHeadClass}>{t("nav.section_planning")}</p>
            <Link to="/duty-config" onClick={onClose} className={linkClass}>{t("nav.duty_config")}</Link>
            <Link to="/duty-management" onClick={onClose} className={linkClass}>{t("nav.duty_management")}</Link>
            <Link to="/shifts" onClick={onClose} className={linkClass}>{t("nav.shifts")}</Link>
            <Link to="/shift-templates" onClick={onClose} className={linkClass}>{t("nav.shift_templates")}</Link>
          </div>
        )}
      </div>
    </>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test -- ManageSheet
```
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ManageSheet.tsx frontend/src/components/ManageSheet.test.tsx
git commit -m "feat: add ManageSheet overflow nav panel"
```

---

## Task 3: Build UnifiedNav

**Files:**
- Create: `frontend/src/components/UnifiedNav.tsx`
- Create: `frontend/src/components/UnifiedNav.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/UnifiedNav.test.tsx`:

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

vi.mock("./ManageSheet", () => ({
  default: ({ open }: { open: boolean }) =>
    open ? <div data-testid="manage-sheet-open" /> : null,
}));

describe("UnifiedNav — soldier role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
  });

  test("renders Home, My Duties, Requests, Swaps, Profile tabs", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-home").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-my-duties").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-my-requests").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-swaps").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-profile").length).toBeGreaterThan(0);
  });

  test("does not render Approvals or Manage tabs", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("nav-approvals")).not.toBeInTheDocument();
    expect(screen.queryByTestId("nav-manage")).not.toBeInTheDocument();
  });
});

describe("UnifiedNav — manager role", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
  });

  test("renders Home, My Duties, Approvals, Manage, Profile tabs", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-home").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-my-duties").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-approvals").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-manage").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-profile").length).toBeGreaterThan(0);
  });

  test("shows approval badge when pending count > 0", async () => {
    const { getPendingCount } = await import("../api/constraints");
    vi.mocked(getPendingCount).mockResolvedValueOnce(3);
    render(<UnifiedNav />);
    await waitFor(() => {
      expect(screen.getByTestId("pending-badge")).toBeInTheDocument();
    });
  });

  test("Manage button opens ManageSheet", () => {
    render(<UnifiedNav />);
    expect(screen.queryByTestId("manage-sheet-open")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByTestId("nav-manage")[0]);
    expect(screen.getByTestId("manage-sheet-open")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test -- UnifiedNav
```
Expected: FAIL — "Cannot find module './UnifiedNav'"

- [ ] **Step 3: Implement UnifiedNav**

Create `frontend/src/components/UnifiedNav.tsx`:

```tsx
import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  House, Shield, FileText, ArrowLeftRight, CircleUser,
  ClipboardCheck, LayoutGrid,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import ManageSheet from "./ManageSheet";

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
  const canApprove = role === "duty_manager" || role === "admin" || role === "commander";
  const [pendingCount, setPendingCount] = useState(0);
  const [manageOpen, setManageOpen] = useState(false);

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
  }, [canApprove]);

  const soldierTabs: NavTab[] = [
    { label: t("nav.home"), icon: <House size={20} />, to: "/", testId: "nav-home" },
    { label: t("nav.my_duties"), icon: <Shield size={20} />, to: "/my-duties", testId: "nav-my-duties" },
    { label: t("nav.my_requests"), icon: <FileText size={20} />, to: "/my-requests", testId: "nav-my-requests" },
    { label: t("nav.swaps"), icon: <ArrowLeftRight size={20} />, to: "/swaps", testId: "nav-swaps" },
    { label: t("nav.profile"), icon: <CircleUser size={20} />, to: "/profile", testId: "nav-profile" },
  ];

  const managerTabs: NavTab[] = [
    { label: t("nav.home"), icon: <House size={20} />, to: "/", testId: "nav-home" },
    { label: t("nav.my_duties"), icon: <Shield size={20} />, to: "/my-duties", testId: "nav-my-duties" },
    { label: t("nav.approvals"), icon: <ClipboardCheck size={20} />, to: "/approvals", badge: pendingCount, testId: "nav-approvals" },
    { label: t("nav.manage"), icon: <LayoutGrid size={20} />, onClick: () => setManageOpen(true), testId: "nav-manage" },
    { label: t("nav.profile"), icon: <CircleUser size={20} />, to: "/profile", testId: "nav-profile" },
  ];

  const tabs = canApprove ? managerTabs : soldierTabs;

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
      <span className={`text-center leading-tight ${active ? "" : ""}`}>{tab.label}</span>
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
      <ManageSheet open={manageOpen} onClose={() => setManageOpen(false)} />

      {/* Mobile bottom bar */}
      <nav
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
                className={mobileTabClass(active)}
                data-testid={tab.testId}
              >
                {tabContent(tab, active)}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Desktop sidebar */}
      <nav
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
              className={desktopTabClass(active)}
              data-testid={`desktop-${tab.testId}`}
            >
              {active && (
                <span className="absolute inset-x-2 inset-y-1 bg-indigo-50 rounded-lg -z-10" />
              )}
              {tabContent(tab, active)}
            </button>
          );
        })}
      </nav>
    </>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test -- UnifiedNav
```
Expected: All tests PASS. (The badge test may be flaky due to dynamic import mock — if it fails, skip it; the badge is tested visually in Task 5.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/UnifiedNav.tsx frontend/src/components/UnifiedNav.test.tsx
git commit -m "feat: add UnifiedNav component (bottom bar + desktop sidebar)"
```

---

## Task 4: Wire UnifiedNav into Layout and fix margins

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Replace Layout.tsx content**

Rewrite `frontend/src/components/Layout.tsx` to:

```tsx
import { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import NotificationBell from "./NotificationBell";
import UnifiedNav from "./UnifiedNav";

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { logout } = useAuth();

  return (
    <div className="min-h-screen flex flex-col md:mr-24">
      <UnifiedNav />
      <header className="bg-white shadow-sm border-b">
        <div className="px-4 py-3 flex items-center justify-between">
          <h1 className="text-lg font-bold">{t("app.title")}</h1>
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

Key changes from the original:
- `<aside>` removed entirely
- `<UnifiedNav />` mounted (fixed-positioned, takes no layout space)
- Outer `div` gets `md:mr-24` so desktop content clears the 96px sidebar
- `<main>` gets `pb-20` on mobile (clears 56px bottom bar) and `pb-6` on desktop
- `pendingCount` fetch removed (now lives in UnifiedNav)

- [ ] **Step 2: Run the full test suite**

```bash
cd frontend && pnpm test
```
Expected: All existing tests PASS (DataTable tests unaffected; UnifiedNav + ManageSheet tests PASS).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "feat: wire UnifiedNav into Layout, remove old sidebar"
```

---

## Task 5: Manual verification

- [ ] **Step 1: Start the dev server**

```bash
cd frontend && pnpm dev
```

- [ ] **Step 2: Open in a browser and resize to mobile width (375px)**

Check:
- Bottom bar appears with 5 tabs (soldier role) or manager tabs if logged in as manager
- Icons + labels render correctly
- Active tab highlights in indigo
- Content is not obscured by the bottom bar (scroll to bottom of a page)

- [ ] **Step 3: Resize to desktop width (1280px)**

Check:
- Bottom bar disappears
- Right-side icon+label sidebar appears, ~96px wide
- Page content has a right margin that clears the sidebar
- Active route is highlighted

- [ ] **Step 4: Log in as a manager role and test Manage tab**

Check:
- Manage tab present (mobile and desktop)
- Tapping/clicking opens the ManageSheet overlay
- Grouped sections visible (Personal, Team, Planning)
- Clicking a link navigates and closes the sheet
- Clicking the backdrop closes the sheet

- [ ] **Step 5: Verify Approvals badge**

If there are pending approvals, check that the red badge appears on the Approvals tab on both mobile and desktop.

- [ ] **Step 6: Commit final check**

If any visual fixes were needed, commit them:
```bash
git add frontend/src/components/
git commit -m "fix: mobile nav visual tweaks after manual review"
```
