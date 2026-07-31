# URL-Param Pagination & Guide Scrollbar Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a shared URL-param pagination convention and migrate the three list pages that currently paginate via local React state (bug reports, announcements, notifications) onto it, and fix a spurious vertical scrollbar in the system guide modal's tab bar.

**Architecture:** Investigation found that, contrary to the original request's premise, the bug-reports page does NOT already use URL-param pagination — no page in the app does. This plan therefore designs a small reusable hook (`usePagePagination`) that reads/writes `page` (and optionally `pageSize`) via `useSearchParams`, styled after the existing `tab`-query-param convention already used in `AdminSettingsPage.tsx`/`SwapsPage.tsx`, then migrates the three known local-state paginated pages onto it.

**Tech Stack:** React/TypeScript, React Router's `useSearchParams`, vitest.

## Global Constraints

- Preserve existing page sizes (`limit = 20` in all three pages) and existing `useQuery` cache-key shapes as much as possible — only the *source* of the offset/page value changes (from `useState` to URL params), not pagination behavior.
- Hebrew UI strings only for any new text.

---

## File Structure

- **Create:** `frontend/src/hooks/usePagePagination.ts` — shared hook: `{ page, setPage, offset, limit }` backed by `useSearchParams`.
- **Modify:** `frontend/src/pages/admin/BugReportsContent.tsx` — replace local `offset` state with the hook.
- **Modify:** `frontend/src/pages/AnnouncementsPage.tsx` — same.
- **Modify:** `frontend/src/pages/NotificationsPage.tsx` — same.
- **Modify:** `frontend/src/components/HelpModal.tsx:1356` — scrollbar CSS fix.
- **Test:** `frontend/src/hooks/usePagePagination.test.ts` (new).

---

### Task 1: Build the shared `usePagePagination` hook

**Files:**
- Create: `frontend/src/hooks/usePagePagination.ts`
- Test: `frontend/src/hooks/usePagePagination.test.ts`

**Interfaces:**
- Produces: `usePagePagination(options: { limit: number; paramName?: string }) => { page: number; setPage: (page: number) => void; offset: number; limit: number }`. `page` is 1-indexed in the URL (`?page=2`) for readability; `offset` is derived as `(page - 1) * limit` for callers that need it (matching the existing `offset`/`limit` shape all three target pages already pass to their list API calls).

- [ ] **Step 1: Write the failing test**

Check whether a hook-testing convention already exists in this repo (search for `renderHook` usage from `@testing-library/react`). Add:

```ts
// frontend/src/hooks/usePagePagination.test.ts
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { usePagePagination } from "./usePagePagination";

function wrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter initialEntries={["/somepage"]}>{children}</MemoryRouter>;
}

describe("usePagePagination", () => {
  it("defaults to page 1, offset 0", () => {
    const { result } = renderHook(() => usePagePagination({ limit: 20 }), { wrapper });
    expect(result.current.page).toBe(1);
    expect(result.current.offset).toBe(0);
    expect(result.current.limit).toBe(20);
  });

  it("setPage updates page and offset together", () => {
    const { result } = renderHook(() => usePagePagination({ limit: 20 }), { wrapper });
    act(() => result.current.setPage(3));
    expect(result.current.page).toBe(3);
    expect(result.current.offset).toBe(40);
  });

  it("reads an initial page from the URL", () => {
    function wrapperWithPage({ children }: { children: React.ReactNode }) {
      return <MemoryRouter initialEntries={["/somepage?page=2"]}>{children}</MemoryRouter>;
    }
    const { result } = renderHook(() => usePagePagination({ limit: 20 }), { wrapper: wrapperWithPage });
    expect(result.current.page).toBe(2);
    expect(result.current.offset).toBe(20);
  });

  it("supports a custom param name so multiple paginated lists can coexist on one page", () => {
    function wrapperWithCustomParam({ children }: { children: React.ReactNode }) {
      return <MemoryRouter initialEntries={["/somepage?otherPage=4"]}>{children}</MemoryRouter>;
    }
    const { result } = renderHook(() => usePagePagination({ limit: 20, paramName: "otherPage" }), { wrapper: wrapperWithCustomParam });
    expect(result.current.page).toBe(4);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/hooks/usePagePagination.test.ts`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement the hook**

```ts
// frontend/src/hooks/usePagePagination.ts
import { useSearchParams } from "react-router-dom";
import { useCallback, useMemo } from "react";

interface Options {
  limit: number;
  paramName?: string;
}

interface Result {
  page: number;
  setPage: (page: number) => void;
  offset: number;
  limit: number;
}

export function usePagePagination({ limit, paramName = "page" }: Options): Result {
  const [searchParams, setSearchParams] = useSearchParams();

  const page = useMemo(() => {
    const raw = Number(searchParams.get(paramName) ?? "1");
    return Number.isFinite(raw) && raw >= 1 ? Math.floor(raw) : 1;
  }, [searchParams, paramName]);

  const setPage = useCallback(
    (next: number) => {
      setSearchParams((prev) => {
        const params = new URLSearchParams(prev);
        if (next <= 1) {
          params.delete(paramName);
        } else {
          params.set(paramName, String(next));
        }
        return params;
      });
    },
    [setSearchParams, paramName]
  );

  return { page, setPage, offset: (page - 1) * limit, limit };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/hooks/usePagePagination.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/usePagePagination.ts frontend/src/hooks/usePagePagination.test.ts
git commit -m "feat: add usePagePagination hook for URL-param-backed list pagination"
```

---

### Task 2: Migrate `BugReportsContent.tsx` to the shared hook

**Files:**
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx:30, 41, 54-63, 67, 316-328`
- Test: manual (behavior-preserving refactor; hook itself is already tested in Task 1)

- [ ] **Step 1: Replace local offset state**

```tsx
// BEFORE (lines 30, 41)
const [offset, setOffset] = useState(0);
...
const limit = 20;
```

```tsx
// AFTER
import { usePagePagination } from "../../hooks/usePagePagination";
...
const { page, setPage, offset, limit } = usePagePagination({ limit: 20 });
```

- [ ] **Step 2: Update the query key**

```tsx
// BEFORE (lines 54-63)
const query = useQuery({
  queryKey: ["bug-reports", severityFilter, statusFilter, offset],
  ...
});
```

```tsx
// AFTER — queryKey unchanged in shape, offset now comes from the hook
const query = useQuery({
  queryKey: ["bug-reports", severityFilter, statusFilter, offset],
  ...
});
```

(No change needed here beyond `offset` now being hook-derived — the key still works identically since `offset` is still a plain number.)

- [ ] **Step 3: Update pagination button clicks**

```tsx
// BEFORE (lines 316-328)
onClick={() => setOffset(i * limit)}
```

```tsx
// AFTER
onClick={() => setPage(i + 1)}
```

(Adjust `i` indexing to match whatever the existing loop variable represents — confirm by reading the surrounding `.map`/loop at lines 316-328 first; the goal is that clicking the button for the `n`-th page sets `page` to `n`.)

Also reset to page 1 when filters change — find where `severityFilter`/`statusFilter` are set (their `onChange` handlers) and ensure `setPage(1)` is called alongside, so changing a filter doesn't leave the URL on a stale out-of-range page.

- [ ] **Step 4: Also filter state to the URL for consistency (optional but recommended for this page since it already has filters)**

Not required by the reported bug (only pagination was mentioned), so treat as optional — skip unless time permits, since scope creep here isn't the ask. Leave `severityFilter`/`statusFilter` as local `useState` as they currently are.

- [ ] **Step 5: Manually verify in the running app**

Start `.\dev.ps1`, log in as admin, go to bug reports, navigate to page 2, confirm the URL now shows `?page=2` (alongside the existing `?tab=` param from `AdminSettingsPage.tsx`), refresh the browser, confirm it stays on page 2. Change a status filter and confirm it resets to page 1.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/admin/BugReportsContent.tsx
git commit -m "feat: persist bug-reports list pagination in URL params"
```

---

### Task 3: Migrate `AnnouncementsPage.tsx` to the shared hook

**Files:**
- Modify: `frontend/src/pages/AnnouncementsPage.tsx:39, 41, 63-64, 113, 247-258`
- Test: manual

- [ ] **Step 1: Replace local offset state**

```tsx
// BEFORE (line 39, 41)
const [offset, setOffset] = useState(0);
const limit = 20;
```

```tsx
// AFTER
import { usePagePagination } from "../hooks/usePagePagination";
const { page, setPage, offset, limit } = usePagePagination({ limit: 20 });
```

- [ ] **Step 2: Update pagination button clicks**

```tsx
// BEFORE (line 252)
onClick={() => setOffset(i * limit)}
```

```tsx
// AFTER
onClick={() => setPage(i + 1)}
```

(Confirm `i` indexing against the real loop at lines 247-258 first.)

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, go to announcements, page forward, confirm `?page=` appears in the URL and survives a refresh.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/AnnouncementsPage.tsx
git commit -m "feat: persist announcements list pagination in URL params"
```

---

### Task 4: Migrate `NotificationsPage.tsx` to the shared hook

**Files:**
- Modify: `frontend/src/pages/NotificationsPage.tsx:12, 13, 16, 49, 96-104`
- Test: manual

- [ ] **Step 1: Replace local offset state**

```tsx
// BEFORE (line 12, 13)
const [offset, setOffset] = useState(0);
const limit = 20;
```

```tsx
// AFTER
import { usePagePagination } from "../hooks/usePagePagination";
const { page, setPage, offset, limit } = usePagePagination({ limit: 20 });
```

- [ ] **Step 2: Update pagination button clicks**

```tsx
// BEFORE (line 99)
onClick={() => setOffset(i * limit)}
```

```tsx
// AFTER
onClick={() => setPage(i + 1)}
```

(Confirm `i` indexing against the real loop at lines 96-104 first.)

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, go to notifications, page forward, confirm `?page=` appears in the URL and survives a refresh.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/NotificationsPage.tsx
git commit -m "feat: persist notifications list pagination in URL params"
```

---

### Task 5: Fix spurious vertical scrollbar in system guide tabs

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx:1356`
- Test: manual (pure CSS fix)

- [ ] **Step 1: Apply the fix**

```tsx
// BEFORE (HelpModal.tsx:1356)
<div className="flex border-b dark:border-gray-600 px-2 pt-1 overflow-x-auto shrink-0" dir="rtl">
```

```tsx
// AFTER
<div className="flex border-b dark:border-gray-600 px-2 pt-1 overflow-x-auto overflow-y-hidden shrink-0" dir="rtl">
```

- [ ] **Step 2: Manually verify in the running app**

Start `.\dev.ps1`, open the help modal (`מדריך המערכת`) on desktop, confirm the tab bar no longer shows a vertical scrollbar. Resize the window narrow enough that tabs overflow horizontally, confirm horizontal scrolling still works.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "fix: remove spurious vertical scrollbar in system guide tab bar"
```

---

## Self-Review Notes

- Both spec items (URL-param pagination "like the bug-reports page" — corrected during investigation to mean "design and apply this pattern," since that page didn't actually have it — and the guide scrollbar) are covered by Tasks 1-5.
- Investigation explicitly found three local-state-paginated pages (bug reports, announcements, notifications); all three are migrated for consistency, not just the one originally named.
- No placeholders; all steps have concrete code, exact file/line targets, and exact commands.
