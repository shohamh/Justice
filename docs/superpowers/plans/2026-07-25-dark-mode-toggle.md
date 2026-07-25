# Dark Mode Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sun/moon/monitor toggle to the app header that cycles Light → Dark → System, persists the choice to the user's profile, and avoids a flash of the wrong theme on load.

**Architecture:** Backend adds a `theme_preference` column to `soldiers` and a `PATCH /me/theme-preference` endpoint (same self-service pattern as the existing `PATCH /me/email`). Frontend switches Tailwind to class-based dark mode, adds a `ThemeContext` that owns the `dark` class on `<html>`, resolves "system" via `matchMedia`, mirrors to `localStorage` for pre-mount application, and calls the new endpoint in the background on change. A small inline script in `index.html` applies the cached class before React mounts.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React + TypeScript + Vite + Tailwind + vitest + `lucide-react` icons (frontend).

## Global Constraints

- Backend self-service preference endpoints (see `PATCH /me/email` in `backend/app/routes/me.py`) require only authentication (`require_password_changed`), no hierarchy `authorize()` check, and no audit log entry — this is a personal UI preference, not a personnel record.
- Allowed `theme_preference` values are exactly `"light" | "dark" | "system"`; validate with a Pydantic `Literal`.
- `frontend/tailwind.config.cjs` `darkMode` must become `"class"` — all existing `dark:` Tailwind classes must keep working unchanged.
- No new database table — a single column on `soldiers` is sufficient (per spec, out of scope: no preferences table).
- No admin-facing control over other users' theme; no other visual/style changes beyond the toggle itself.
- Run only targeted tests per task (`pytest <path> -q`, `npx vitest run <path>`), not the full suite — full suite only at release per project convention.

---

### Task 1: Backend — `theme_preference` column + migration

**Files:**
- Modify: `backend/app/db/models.py` (add column to `Soldier`, near other simple `Text`-typed fields like `email` around line 42)
- Create: `backend/alembic/versions/0065_add_theme_preference_to_soldiers.py`
- Test: `backend/tests/integration/test_me_capabilities.py` (extend — verifies the field round-trips through `/api/me`)

**Interfaces:**
- Produces: `Soldier.theme_preference: str` (SQLAlchemy `Mapped[str]`, default `"system"`) — consumed by Task 2 (route) and Task 3 (schema).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_me_capabilities.py`:

```python
def test_me_defaults_theme_preference_to_system(client, admin_session):
    from tests.helpers import create_soldier, auth_headers

    s = create_soldier(admin_session, personal_number="7600022")
    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    assert r.json()["theme_preference"] == "system"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_me_capabilities.py::test_me_defaults_theme_preference_to_system -v`
Expected: FAIL — `KeyError: 'theme_preference'` (the field doesn't exist in the response yet).

- [ ] **Step 3: Add the column to the `Soldier` model**

In `backend/app/db/models.py`, inside `class Soldier(Base):`, add near the other `Text`-typed simple fields (e.g. right after the `email_verified` field around line 43):

```python
    theme_preference: Mapped[str] = mapped_column(
        Text, server_default=text("'system'"), default="system"
    )
```

- [ ] **Step 4: Write the Alembic migration**

Create `backend/alembic/versions/0065_add_theme_preference_to_soldiers.py`:

```python
"""add_theme_preference_to_soldiers

Revision ID: 0065
Revises: 71e217f7c372
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0065'
down_revision: Union[str, Sequence[str], None] = '71e217f7c372'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "soldiers",
        sa.Column("theme_preference", sa.Text(), nullable=False, server_default="system"),
    )


def downgrade() -> None:
    op.drop_column("soldiers", "theme_preference")
```

- [ ] **Step 5: Apply the migration**

Run: `alembic upgrade head`
Expected: migration `0065` applies cleanly with no errors.

- [ ] **Step 6: Add the field to `MeResponse` and the `me()` handler**

This is needed for the Step-1 test to pass — do it here rather than deferring to Task 3, since the test targets `/api/me`. In `backend/app/routes/me.py`:

In `class MeResponse(BaseModel):`, add after `enrollment_pending: bool = False`:

```python
    theme_preference: str = "system"
```

In the `me()` handler's `return MeResponse(...)`, add after `enrollment_pending=enrollment_pending,`:

```python
        theme_preference=user.theme_preference,
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/integration/test_me_capabilities.py::test_me_defaults_theme_preference_to_system -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0065_add_theme_preference_to_soldiers.py backend/app/routes/me.py backend/tests/integration/test_me_capabilities.py
git commit -m "feat: add theme_preference column to soldiers"
```

---

### Task 2: Backend — `PATCH /me/theme-preference` endpoint

**Files:**
- Modify: `backend/app/routes/me.py`
- Test: Create `backend/tests/integration/test_theme_preference_api.py`

**Interfaces:**
- Consumes: `Soldier.theme_preference` (Task 1).
- Produces: `PATCH /api/me/theme-preference` with body `{"theme_preference": "light"|"dark"|"system"}` → `200 {"theme_preference": "..."}`. Consumed by Task 5 (frontend API wrapper).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_theme_preference_api.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_update_theme_preference_persists(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7600023")

    r = client.patch(
        "/api/me/theme-preference",
        headers=auth_headers(s),
        json={"theme_preference": "dark"},
    )
    assert r.status_code == 200
    assert r.json() == {"theme_preference": "dark"}

    r2 = client.get("/api/me", headers=auth_headers(s))
    assert r2.json()["theme_preference"] == "dark"


def test_update_theme_preference_rejects_invalid_value(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7600024")

    r = client.patch(
        "/api/me/theme-preference",
        headers=auth_headers(s),
        json={"theme_preference": "purple"},
    )
    assert r.status_code == 422


def test_update_theme_preference_requires_auth(client: TestClient):
    r = client.patch("/api/me/theme-preference", json={"theme_preference": "dark"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_theme_preference_api.py -v`
Expected: FAIL — `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Add the request/response models and route**

In `backend/app/routes/me.py`, add after `class SetEmailRequest(BaseModel):` (around line 55):

```python
class ThemePreferenceRequest(BaseModel):
    theme_preference: Literal["light", "dark", "system"]


class ThemePreferenceResponse(BaseModel):
    theme_preference: str
```

Add `Literal` to the existing `typing` import at the top of the file (currently `from typing import Annotated` — change to `from typing import Annotated, Literal`).

Add the route after `set_email` (end of file):

```python
@router.patch("/theme-preference", response_model=ThemePreferenceResponse)
def set_theme_preference(
    body: ThemePreferenceRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ThemePreferenceResponse:
    user.theme_preference = body.theme_preference
    session.commit()
    return ThemePreferenceResponse(theme_preference=user.theme_preference)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_theme_preference_api.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/me.py backend/tests/integration/test_theme_preference_api.py
git commit -m "feat: add PATCH /me/theme-preference endpoint"
```

---

### Task 3: Frontend — `Me` type, API wrapper, Tailwind class-mode

**Files:**
- Modify: `frontend/src/api/auth.ts` (add `theme_preference` to `Me` interface)
- Create: `frontend/src/api/theme.ts`
- Modify: `frontend/tailwind.config.cjs` (`darkMode: "media"` → `"class"`)
- Test: Create `frontend/src/api/theme.test.ts`

**Interfaces:**
- Consumes: nothing new (uses existing `api` client from `frontend/src/api/client.ts`).
- Produces: `Me.theme_preference: "light" | "dark" | "system"`; `updateThemePreference(theme: "light" | "dark" | "system"): Promise<"light" | "dark" | "system">` — consumed by Task 4 (`ThemeContext`).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/api/theme.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";

const mockPatch = vi.fn();
vi.mock("./client", () => ({
  api: { patch: (...args: unknown[]) => mockPatch(...args) },
}));

describe("updateThemePreference", () => {
  it("PATCHes /me/theme-preference and returns the saved value", async () => {
    mockPatch.mockResolvedValue({ data: { theme_preference: "dark" } });
    const { updateThemePreference } = await import("./theme");

    const result = await updateThemePreference("dark");

    expect(mockPatch).toHaveBeenCalledWith("/me/theme-preference", { theme_preference: "dark" });
    expect(result).toBe("dark");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/api/theme.test.ts`
Expected: FAIL — cannot find module `./theme`.

- [ ] **Step 3: Add `theme_preference` to the `Me` interface**

In `frontend/src/api/auth.ts`, inside `export interface Me { ... }`, add after `enrollment_pending: boolean;`:

```typescript
  theme_preference: "light" | "dark" | "system";
```

- [ ] **Step 4: Create the API wrapper**

Create `frontend/src/api/theme.ts`:

```typescript
import { api } from "./client";

export type ThemePreference = "light" | "dark" | "system";

export async function updateThemePreference(theme: ThemePreference): Promise<ThemePreference> {
  const r = await api.patch<{ theme_preference: ThemePreference }>("/me/theme-preference", {
    theme_preference: theme,
  });
  return r.data.theme_preference;
}
```

- [ ] **Step 5: Switch Tailwind to class-based dark mode**

In `frontend/tailwind.config.cjs`, change:

```javascript
  darkMode: "media",
```

to:

```javascript
  darkMode: "class",
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npx vitest run src/api/theme.test.ts`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/auth.ts frontend/src/api/theme.ts frontend/src/api/theme.test.ts frontend/tailwind.config.cjs
git commit -m "feat: add theme preference API wrapper, switch tailwind to class-based dark mode"
```

---

### Task 4: Frontend — `ThemeContext` + pre-mount flash prevention

**Files:**
- Create: `frontend/src/theme/ThemeContext.tsx`
- Create: `frontend/src/theme/ThemeContext.test.tsx`
- Modify: `frontend/index.html` (inline pre-mount script)
- Modify: `frontend/src/main.tsx` (wrap app with `ThemeProvider`)

**Interfaces:**
- Consumes: `updateThemePreference` and `ThemePreference` type (Task 3); `useAuth()` (`user`, `refreshMe`) from `frontend/src/auth/AuthContext.tsx`.
- Produces: `ThemeProvider` component; `useTheme(): { theme: ThemePreference; resolvedTheme: "light" | "dark"; cycleTheme: () => void }` — consumed by Task 5 (`Layout.tsx` toggle button).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/theme/ThemeContext.test.tsx`:

```typescript
import { render, screen, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const mockUpdateThemePreference = vi.fn();
vi.mock("../api/theme", () => ({
  updateThemePreference: (...args: unknown[]) => mockUpdateThemePreference(...args),
}));

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

function Probe() {
  const { useTheme } = require("./ThemeContext");
  const { theme, resolvedTheme, cycleTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="resolved">{resolvedTheme}</span>
      <button onClick={cycleTheme}>cycle</button>
    </div>
  );
}

describe("ThemeContext", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
    mockUpdateThemePreference.mockReset().mockResolvedValue("dark");
    mockUseAuth.mockReturnValue({ user: null });
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })));
  });

  it("cycles light -> dark -> system -> light and applies the dark class", async () => {
    const { ThemeProvider } = await import("./ThemeContext");
    localStorage.setItem("theme", "light");
    render(<ThemeProvider><Probe /></ThemeProvider>);

    expect(screen.getByTestId("theme").textContent).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    act(() => screen.getByText("cycle").click());
    await waitFor(() => expect(screen.getByTestId("theme").textContent).toBe("dark"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(mockUpdateThemePreference).toHaveBeenCalledWith("dark");

    act(() => screen.getByText("cycle").click());
    await waitFor(() => expect(screen.getByTestId("theme").textContent).toBe("system"));

    act(() => screen.getByText("cycle").click());
    await waitFor(() => expect(screen.getByTestId("theme").textContent).toBe("light"));
  });

  it("adopts the profile's theme_preference once the user loads, overriding localStorage", async () => {
    localStorage.setItem("theme", "light");
    mockUseAuth.mockReturnValue({ user: { theme_preference: "dark" } });
    const { ThemeProvider } = await import("./ThemeContext");
    render(<ThemeProvider><Probe /></ThemeProvider>);

    await waitFor(() => expect(screen.getByTestId("theme").textContent).toBe("dark"));
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/theme/ThemeContext.test.tsx`
Expected: FAIL — cannot find module `./ThemeContext`.

- [ ] **Step 3: Implement `ThemeContext`**

Create `frontend/src/theme/ThemeContext.tsx`:

```typescript
import { createContext, useCallback, useContext, useEffect, useMemo, useState, ReactNode } from "react";

import { updateThemePreference, ThemePreference } from "../api/theme";
import { useAuth } from "../auth/AuthContext";

const STORAGE_KEY = "theme";
const ORDER: ThemePreference[] = ["light", "dark", "system"];

function resolveSystemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyThemeClass(theme: ThemePreference) {
  const isDark = theme === "dark" || (theme === "system" && resolveSystemPrefersDark());
  document.documentElement.classList.toggle("dark", isDark);
}

interface ThemeContextValue {
  theme: ThemePreference;
  resolvedTheme: "light" | "dark";
  cycleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [theme, setThemeState] = useState<ThemePreference>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
  });

  const setTheme = useCallback((next: ThemePreference, sync: boolean) => {
    setThemeState(next);
    localStorage.setItem(STORAGE_KEY, next);
    applyThemeClass(next);
    if (sync) {
      updateThemePreference(next).catch(() => {
        // Optimistic: choice already persisted locally for this device;
        // a failed sync just means it isn't saved to the profile yet.
      });
    }
  }, []);

  // Adopt the profile's value once known — it's authoritative once loaded;
  // localStorage only bridges the pre-auth/first-paint moment.
  useEffect(() => {
    if (user && user.theme_preference !== theme) {
      setTheme(user.theme_preference, false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.theme_preference]);

  // Live-follow OS changes while in "system" mode.
  useEffect(() => {
    if (theme !== "system") return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => applyThemeClass("system");
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [theme]);

  const cycleTheme = useCallback(() => {
    const next = ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length];
    setTheme(next, true);
  }, [theme, setTheme]);

  const resolvedTheme: "light" | "dark" = useMemo(
    () => (theme === "dark" || (theme === "system" && resolveSystemPrefersDark()) ? "dark" : "light"),
    [theme],
  );

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, resolvedTheme, cycleTheme }),
    [theme, resolvedTheme, cycleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme used outside ThemeProvider");
  return ctx;
}
```

- [ ] **Step 4: Add the pre-mount script to `index.html`**

In `frontend/index.html`, add inside `<head>`, right after the `<title>` tag:

```html
    <script>
      (function () {
        var stored = localStorage.getItem("theme");
        var isDark =
          stored === "dark" ||
          (stored !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
        if (isDark) document.documentElement.classList.add("dark");
      })();
    </script>
```

- [ ] **Step 5: Wrap the app with `ThemeProvider` in `main.tsx`**

In `frontend/src/main.tsx`, add the import:

```typescript
import { ThemeProvider } from "./theme/ThemeContext";
```

Wrap `<App />` (the `ThemeProvider` needs `useAuth()`, so it must go inside wherever `AuthProvider` is mounted — check `frontend/src/App.tsx` for where `AuthProvider` wraps routes; if `AuthProvider` is inside `App.tsx` rather than `main.tsx`, add `ThemeProvider` there instead, nested inside `AuthProvider`). Render structure in `main.tsx` becomes:

```typescript
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AlgorithmSeenProvider>
          <App />
        </AlgorithmSeenProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

Before editing, grep `frontend/src/App.tsx` for `AuthProvider` to confirm its exact nesting location, then add `<ThemeProvider>` as a direct child wrapping whatever `AuthProvider` wraps (so `useAuth()` inside `ThemeProvider` resolves correctly). Do not guess the nesting — read the file first.

- [ ] **Step 6: Run tests to verify they pass**

Run: `npx vitest run src/theme/ThemeContext.test.tsx`
Expected: PASS (both tests)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/theme/ThemeContext.tsx frontend/src/theme/ThemeContext.test.tsx frontend/index.html frontend/src/main.tsx
git commit -m "feat: add ThemeContext with pre-mount flash prevention"
```

(If Step 5 required editing `frontend/src/App.tsx` instead of/in addition to `main.tsx`, include it in this `git add`.)

---

### Task 5: Frontend — header toggle button

**Files:**
- Modify: `frontend/src/components/Layout.tsx`
- Test: Create `frontend/src/components/Layout.test.tsx`

**Interfaces:**
- Consumes: `useTheme()` (Task 4) — `{ theme, resolvedTheme, cycleTheme }`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Layout.test.tsx`:

```typescript
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";

const mockCycleTheme = vi.fn();
let mockTheme = "light";
vi.mock("../theme/ThemeContext", () => ({
  useTheme: () => ({ theme: mockTheme, resolvedTheme: "light", cycleTheme: mockCycleTheme }),
}));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ logout: vi.fn(), user: { role: "soldier" } }),
}));
vi.mock("../api/publicSettings", () => ({
  getPublicSettings: () => Promise.resolve({}),
}));

describe("Layout theme toggle", () => {
  it("renders the toggle and calls cycleTheme on click", async () => {
    mockTheme = "light";
    const { default: Layout } = await import("./Layout");
    render(
      <MemoryRouter>
        <Layout>children</Layout>
      </MemoryRouter>,
    );

    const toggle = screen.getByTestId("theme-toggle-button");
    act(() => toggle.click());
    expect(mockCycleTheme).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/Layout.test.tsx`
Expected: FAIL — `Unable to find an element by [data-testid="theme-toggle-button"]`.

- [ ] **Step 3: Add the toggle button to `Layout.tsx`**

In `frontend/src/components/Layout.tsx`:

Add to the imports (line 4): change

```typescript
import { CircleUser, Settings, HelpCircle } from "lucide-react";
```

to:

```typescript
import { CircleUser, Settings, HelpCircle, Sun, Moon, Monitor } from "lucide-react";
```

Add the `useTheme` import after the `useAuth` import (line 5):

```typescript
import { useTheme } from "../theme/ThemeContext";
```

Inside the component, after `const { logout, user } = useAuth();` (line 14), add:

```typescript
  const { theme, cycleTheme } = useTheme();
  const themeIcon = theme === "light" ? <Sun size={22} /> : theme === "dark" ? <Moon size={22} /> : <Monitor size={22} />;
  const themeLabel =
    theme === "light" ? "מצב תאורה: בהיר (לחץ למעבר לכהה)" :
    theme === "dark" ? "מצב תאורה: כהה (לחץ למעבר לפי מערכת)" :
    "מצב תאורה: לפי מערכת (לחץ למעבר לבהיר)";
```

In the right-side icon group (currently lines 52-68), add the toggle button before the help button:

```typescript
          <div className="flex items-center gap-4">
            <button
              onClick={cycleTheme}
              aria-label={themeLabel}
              title={themeLabel}
              data-testid="theme-toggle-button"
              className="text-gray-500 hover:text-indigo-600"
            >
              {themeIcon}
            </button>
            <button
              onClick={() => openHelp()}
              aria-label="עזרה"
              className="text-gray-500 hover:text-indigo-600"
            >
              <HelpCircle size={22} />
            </button>
            <NotificationBell />
            <button
              onClick={() => logout()}
              className="text-sm text-indigo-600 dark:text-indigo-300 hover:text-indigo-800 dark:hover:text-indigo-200"
              data-testid="logout-button"
            >
              {t("home.logout")}
            </button>
          </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/Layout.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout.tsx frontend/src/components/Layout.test.tsx
git commit -m "feat: add sun/moon/system theme toggle to header"
```

---

### Task 6: Manual verification in the browser

**Files:** none (verification only).

- [ ] **Step 1: Start the dev stack**

Run: `.\dev.ps1` from the repo root (per `CLAUDE.md`).

- [ ] **Step 2: Log in and verify the toggle cycles correctly**

Open `http://localhost:5173`, log in, and in the header click the new theme icon (next to the help icon). Confirm:
- First click: page switches to dark styling, icon becomes a moon.
- Second click: icon becomes a monitor, page follows current OS theme.
- Third click: back to sun icon, light styling.

- [ ] **Step 3: Verify persistence across reload and devices**

Set the toggle to "dark", then hard-refresh the page. Confirm no flash of light mode before dark styling applies, and the toggle still reads "dark". Log out and back in (or open the app in a different browser profile logged into the same account) and confirm the theme is "dark" there too (proves it's read from the profile, not just `localStorage`).

- [ ] **Step 4: Verify "system" mode follows OS changes live**

Set the toggle to "system" (monitor icon). Toggle the OS-level dark mode setting (or, in Chrome DevTools, Rendering tab → "Emulate CSS media feature prefers-color-scheme"). Confirm the page's styling updates without a manual reload.

---

## Self-Review

**Spec coverage:**
- Backend `theme_preference` column + endpoint — Tasks 1, 2. ✓
- Tailwind class-mode switch — Task 3. ✓
- Pre-mount flash prevention via inline script + localStorage — Task 4. ✓
- `ThemeContext` cycling, system live-follow, profile-as-source-of-truth — Task 4. ✓
- Header toggle button, sun/moon/monitor icons, Hebrew `aria-label` — Task 5. ✓
- Optimistic instant apply + background save — Task 4 `setTheme`. ✓
- Backend and frontend targeted tests — every task. ✓
- Manual browser verification — Task 6. ✓

**Placeholder scan:** No TBD/TODO markers; every step has complete code.

**Type consistency:** `ThemePreference` type (`"light" | "dark" | "system"`) defined once in `frontend/src/api/theme.ts` and reused in `ThemeContext.tsx` and `Layout.tsx` via `theme` from `useTheme()`. Backend `Literal["light", "dark", "system"]` in `ThemePreferenceRequest` matches the column's allowed values. `useTheme()` return shape (`theme`, `resolvedTheme`, `cycleTheme`) is defined in Task 4 and consumed identically in Task 5's test mock and implementation.
