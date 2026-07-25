# Searchable Tabs and Panels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the global header search so it can find and jump directly to specific tabs within Admin Settings, Approvals, Swaps, and Transparency, showing results as `"PageName > TabName"`, and apply the same prefix convention to existing help-topic results.

**Architecture:** All four target pages already read their active tab from a `?tab=` URL param on mount, so no page code changes are needed. A new `TabEntry` registry (mirroring the existing `PageEntry`/`QuickActionEntry`/`HelpTopicEntry` pattern in `frontend/src/searchRegistry.ts`) supplies the 12 non-default tabs; `HeaderSearch.tsx` fuzzy-matches them with a new Fuse index and navigates to `path?tab=value` on selection.

**Tech Stack:** React + TypeScript, Fuse.js (fuzzy search, already a dependency), react-i18next, vitest + @testing-library/react.

## Global Constraints

- Only the 4 pages with an existing `?tab=` mechanism are in scope: Admin Settings (`/admin/settings`), Approvals (`/approvals`), Swaps (`/swaps`), Transparency (`/transparency`). Import Session Review is explicitly excluded (no fixed URL — requires a dynamic session ID).
- Only **non-default** tabs get registry entries (12 total) — each page's default tab is already reachable via its existing `PageEntry`, so a tab-specific entry for it would duplicate that with a confusing `"PageName > PageName"` label.
- Every tab entry's `labelKey` reuses the exact i18n key the page's own tab button already renders (verified against `frontend/src/i18n/he.json` — see table below) — do not introduce duplicate label strings.
- `canAccess` for every tab reuses its parent page's existing access-check function from `searchRegistry.ts` (`isAdmin` for Admin Settings, `canApprove` for Approvals, `authenticated` for Swaps and Transparency) — never write a new access predicate.
- Help-topic results change from showing just their own label to `"עזרה > <topic>"` (prefix with the existing `search.categories.help` key) — no change to `HelpModal` or `getHelpTopicEntries()` themselves.
- No backend changes — this is entirely frontend-registry-driven.

---

### Task 1: `TabEntry` registry + i18n keys

**Files:**
- Modify: `frontend/src/searchRegistry.ts`
- Modify: `frontend/src/i18n/he.json`
- Test: `frontend/src/searchRegistry.test.ts`

**Interfaces:**
- Produces: `export interface TabEntry { id: string; pageLabelKey: string; labelKey: string; keywords: string[]; path: string; tabParam: string; canAccess: (user: SearchUser | null) => boolean; }` and `export function getTabEntries(): TabEntry[]` — consumed by Task 2.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/searchRegistry.test.ts`, after the existing `describe("searchRegistry help topics", ...)` block, and update the import line at the top of the file:

```typescript
import { getPageEntries, getQuickActionEntries, getHelpTopicEntries, getTabEntries } from "./searchRegistry";
```

```typescript
describe("searchRegistry tabs", () => {
  test("returns exactly 12 tab entries", () => {
    expect(getTabEntries().length).toBe(12);
  });

  test("admin settings tabs require admin role", () => {
    const entries = getTabEntries();
    const inviteCodes = entries.find((e) => e.id === "tab-admin-invite-codes")!;
    expect(inviteCodes.canAccess(soldier)).toBe(false);
    expect(inviteCodes.canAccess(admin)).toBe(true);
  });

  test("approvals tabs require approval capability", () => {
    const entries = getTabEntries();
    const exemptions = entries.find((e) => e.id === "tab-approvals-exemptions")!;
    expect(exemptions.canAccess(soldier)).toBe(false);
    expect(exemptions.canAccess(commander)).toBe(true);
    expect(exemptions.canAccess(dutyManager)).toBe(true);
  });

  test("swaps and transparency tabs are accessible to any authenticated user", () => {
    const entries = getTabEntries();
    expect(entries.find((e) => e.id === "tab-swaps-board")!.canAccess(soldier)).toBe(true);
    expect(entries.find((e) => e.id === "tab-transparency-sub-units")!.canAccess(soldier)).toBe(true);
  });

  test("no tab entry is accessible with a null user", () => {
    expect(getTabEntries().every((e) => e.canAccess(null) === false)).toBe(true);
  });

  test("each tab entry within the same page has a distinct tabParam", () => {
    const entries = getTabEntries();
    const approvalsTabs = entries.filter((e) => e.path === "/approvals");
    const params = approvalsTabs.map((e) => e.tabParam);
    expect(new Set(params).size).toBe(params.length);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/searchRegistry.test.ts`
Expected: FAIL — `getTabEntries` is not exported from `./searchRegistry`.

- [ ] **Step 3: Add the `TabEntry` type and `getTabEntries()` function**

In `frontend/src/searchRegistry.ts`, add after the existing `getHelpTopicEntries` function (end of file):

```typescript
export interface TabEntry {
  id: string;
  pageLabelKey: string;
  labelKey: string;
  keywords: string[];
  path: string;
  tabParam: string;
  canAccess: (user: SearchUser | null) => boolean;
}

export function getTabEntries(): TabEntry[] {
  return [
    { id: "tab-admin-invite-codes", pageLabelKey: "search.pages.admin_settings", labelKey: "nav.admin_invite_codes", keywords: ["קודי הזמנה", "הזמנות", "הרשמה"], path: "/admin/settings", tabParam: "1", canAccess: isAdmin },
    { id: "tab-admin-changelog", pageLabelKey: "search.pages.admin_settings", labelKey: "nav.admin_changelog", keywords: ["יומן שינויים", "עדכונים", "גרסאות"], path: "/admin/settings", tabParam: "2", canAccess: isAdmin },
    { id: "tab-admin-bug-reports", pageLabelKey: "search.pages.admin_settings", labelKey: "nav.admin_bug_reports", keywords: ["דיווחי באגים", "באגים", "תקלות"], path: "/admin/settings", tabParam: "3", canAccess: isAdmin },
    { id: "tab-approvals-exemptions", pageLabelKey: "search.pages.approvals", labelKey: "approvals.tab_exemptions", keywords: ["בקשות פטור", "פטורים"], path: "/approvals", tabParam: "exemptions", canAccess: canApprove },
    { id: "tab-approvals-field-updates", pageLabelKey: "search.pages.approvals", labelKey: "soldier_profile.field_updates_tab", keywords: ["עדכוני פרופיל", "שינויי פרטים"], path: "/approvals", tabParam: "field_updates", canAccess: canApprove },
    { id: "tab-approvals-swaps", pageLabelKey: "search.pages.approvals", labelKey: "swaps.title", keywords: ["בקשות החלפה", "אישור החלפות"], path: "/approvals", tabParam: "swaps", canAccess: canApprove },
    { id: "tab-approvals-enrollment", pageLabelKey: "search.pages.approvals", labelKey: "enrollment.tab", keywords: ["הצטרפות", "גיוס", "קליטה"], path: "/approvals", tabParam: "enrollment", canAccess: canApprove },
    { id: "tab-approvals-transfers", pageLabelKey: "search.pages.approvals", labelKey: "approvals.tab_transfers", keywords: ["העברות", "מעבר יחידה"], path: "/approvals", tabParam: "transfers", canAccess: canApprove },
    { id: "tab-swaps-board", pageLabelKey: "search.pages.swaps", labelKey: "swaps.tab_board", keywords: ["מרקטפלייס", "לוח החלפות"], path: "/swaps", tabParam: "board", canAccess: authenticated },
    { id: "tab-swaps-incoming", pageLabelKey: "search.pages.swaps", labelKey: "swaps.tab_incoming", keywords: ["בקשות אליי", "בקשות נכנסות"], path: "/swaps", tabParam: "incoming", canAccess: authenticated },
    { id: "tab-swaps-pending", pageLabelKey: "search.pages.swaps", labelKey: "swaps.tab_pending", keywords: ["ממתינים לאישור", "החלפות בהמתנה"], path: "/swaps", tabParam: "pending", canAccess: authenticated },
    { id: "tab-transparency-sub-units", pageLabelKey: "search.pages.transparency", labelKey: "search.tabs.transparency_sub_units", keywords: ["תתי יחידות", "יחידות משנה"], path: "/transparency", tabParam: "sub_units", canAccess: authenticated },
  ];
}
```

- [ ] **Step 4: Add the new i18n keys**

In `frontend/src/i18n/he.json`, the `search.categories` object currently ends with:

```json
      "help": "עזרה"
    },
```

Change to:

```json
      "help": "עזרה",
      "tab": "לשונית"
    },
```

The `search.help` object (and the whole file) currently ends with:

```json
      "gimelim": "🏥 גימלים"
    }
  }
}
```

Change to:

```json
      "gimelim": "🏥 גימלים"
    },
    "tabs": {
      "transparency_sub_units": "תתי יחידות"
    }
  }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npx vitest run src/searchRegistry.test.ts`
Expected: PASS (all tests, including the 5 new ones)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/searchRegistry.ts frontend/src/i18n/he.json frontend/src/searchRegistry.test.ts
git commit -m "feat: add searchable tab registry for admin settings, approvals, swaps, transparency"
```

---

### Task 2: Wire tabs into `HeaderSearch` + re-prefix help results

**Files:**
- Modify: `frontend/src/components/HeaderSearch.tsx`
- Test: `frontend/src/components/HeaderSearch.test.tsx`

**Interfaces:**
- Consumes: `getTabEntries()` and `TabEntry` (Task 1); existing `search.categories.help` i18n key (already present).

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/HeaderSearch.test.tsx`, first update the existing help-topic test (line ~215-221) — the label now carries the `"עזרה > "` prefix (rendered as the raw key `"search.categories.help > "` under the test's identity-mock `t`):

Replace:

```typescript
  test("clicking a help-topic result calls openHelp with that topic's id", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "algorithm" } });
    fireEvent.click(screen.getByText("search.help.algorithm"));
    expect(mockOpenHelp).toHaveBeenCalledWith("algorithm");
  });
```

With:

```typescript
  test("clicking a help-topic result calls openHelp with that topic's id", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "algorithm" } });
    fireEvent.click(screen.getByText("search.categories.help > search.help.algorithm"));
    expect(mockOpenHelp).toHaveBeenCalledWith("algorithm");
  });
```

Then add three new tests at the end of the `describe("HeaderSearch", ...)` block, right before the final closing `});`:

```typescript
  test("typing a tab keyword surfaces it with a 'Page > Tab' label", () => {
    mockUseAuth.mockReturnValue({ user: { role: "admin", is_commander: false, is_duty_manager: false } });
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "קודי הזמנה" } });
    expect(screen.getByText("search.pages.admin_settings > nav.admin_invite_codes")).toBeInTheDocument();
  });

  test("selecting a tab result navigates to the page with the tab query param", () => {
    mockUseAuth.mockReturnValue({ user: { role: "admin", is_commander: false, is_duty_manager: false } });
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "קודי הזמנה" } });
    fireEvent.click(screen.getByText("search.pages.admin_settings > nav.admin_invite_codes"));
    expect(mockNavigate).toHaveBeenCalledWith("/admin/settings?tab=1");
  });

  test("tab results are excluded for a user without page access", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "קודי הזמנה" } });
    expect(screen.queryByText("search.pages.admin_settings > nav.admin_invite_codes")).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/components/HeaderSearch.test.tsx`
Expected: FAIL — the updated help-topic test fails (old label text still rendered), and the 3 new tests fail (`getTabEntries` not yet consumed, no tab results rendered).

- [ ] **Step 3: Update `HeaderSearch.tsx`**

In `frontend/src/components/HeaderSearch.tsx`:

Change the import block (lines 9-16) from:

```typescript
import {
  getPageEntries,
  getQuickActionEntries,
  getHelpTopicEntries,
  type PageEntry,
  type QuickActionEntry,
  type HelpTopicEntry,
} from "../searchRegistry";
```

to:

```typescript
import {
  getPageEntries,
  getQuickActionEntries,
  getHelpTopicEntries,
  getTabEntries,
  type PageEntry,
  type QuickActionEntry,
  type HelpTopicEntry,
  type TabEntry,
} from "../searchRegistry";
```

Add `"tab"` to the `FlatResult` union (line 18-24), inserting after the `"help"` variant:

```typescript
type FlatResult =
  | { kind: "page"; key: string; entry: PageEntry }
  | { kind: "action"; key: string; entry: QuickActionEntry }
  | { kind: "help"; key: string; entry: HelpTopicEntry }
  | { kind: "tab"; key: string; entry: TabEntry }
  | { kind: "soldier"; key: string; entry: SearchResponseDTO["soldiers"][number] }
  | { kind: "duty"; key: string; entry: SearchResponseDTO["duties"][number] }
  | { kind: "unit"; key: string; entry: SearchResponseDTO["units"][number] };
```

After the existing `accessibleHelp` memo (around line 43-46), add:

```typescript
  const accessibleTabs = useMemo(() => getTabEntries().filter((e) => e.canAccess(user)), [user]);
```

After the existing `helpFuse` memo (line 50), add:

```typescript
  const tabFuse = useMemo(() => new Fuse(accessibleTabs, { keys: ["keywords"], threshold: 0.4 }), [accessibleTabs]);
```

After the existing `helpResults` line (line 55), add:

```typescript
  const tabResults = trimmed ? tabFuse.search(trimmed).map((r) => r.item).slice(0, 8) : [];
```

In the `flatResults` array (lines 85-92), add a line for tabs after the `helpResults` spread:

```typescript
  const flatResults: FlatResult[] = [
    ...pageResults.map((entry) => ({ kind: "page" as const, key: `page-${entry.id}`, entry })),
    ...actionResults.map((entry) => ({ kind: "action" as const, key: `action-${entry.id}`, entry })),
    ...helpResults.map((entry) => ({ kind: "help" as const, key: `help-${entry.id}`, entry })),
    ...tabResults.map((entry) => ({ kind: "tab" as const, key: `tab-${entry.id}`, entry })),
    ...backendResults.soldiers.map((entry) => ({ kind: "soldier" as const, key: `soldier-${entry.id}`, entry })),
    ...backendResults.duties.map((entry) => ({ kind: "duty" as const, key: `duty-${entry.id}`, entry })),
    ...backendResults.units.map((entry) => ({ kind: "unit" as const, key: `unit-${entry.id}`, entry })),
  ];
```

In `handleSelect` (lines 106-124), add a case for `"tab"` after the `"help"` case:

```typescript
  function handleSelect(r: FlatResult) {
    switch (r.kind) {
      case "page":
      case "action":
        navigate(r.entry.path);
        break;
      case "help":
        openHelp(r.entry.id);
        break;
      case "tab":
        navigate(`${r.entry.path}?tab=${r.entry.tabParam}`);
        break;
      case "soldier":
        navigate("/team");
        break;
      case "duty":
      case "unit":
        navigate("/unit-calendar");
        break;
    }
    closePanel();
  }
```

In `labelFor` (lines 145-160), change the `"help"` case and add a `"tab"` case:

```typescript
  function labelFor(r: FlatResult): string {
    switch (r.kind) {
      case "page":
        return t(r.entry.labelKey);
      case "action":
        return t(r.entry.labelKey);
      case "help":
        return `${t("search.categories.help")} > ${t(r.entry.labelKey)}`;
      case "tab":
        return `${t(r.entry.pageLabelKey)} > ${t(r.entry.labelKey)}`;
      case "soldier":
        return r.entry.full_name;
      case "duty":
        return r.entry.duty_type_name;
      case "unit":
        return r.entry.name;
    }
  }
```

In the `groups` array (lines 191-198), add a new group for tabs after the help group:

```typescript
  const groups: { titleKey: string; icon: string; items: FlatResult[] }[] = [
    { titleKey: "search.categories.page", icon: "📄", items: flatResults.filter((r) => r.kind === "page") },
    { titleKey: "search.categories.action", icon: "⚡", items: flatResults.filter((r) => r.kind === "action") },
    { titleKey: "search.categories.help", icon: "❓", items: flatResults.filter((r) => r.kind === "help") },
    { titleKey: "search.categories.tab", icon: "📑", items: flatResults.filter((r) => r.kind === "tab") },
    { titleKey: "search.categories.soldier", icon: "👤", items: flatResults.filter((r) => r.kind === "soldier") },
    { titleKey: "search.categories.duty", icon: "📅", items: flatResults.filter((r) => r.kind === "duty") },
    { titleKey: "search.categories.unit", icon: "🏛️", items: flatResults.filter((r) => r.kind === "unit") },
  ];
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/components/HeaderSearch.test.tsx`
Expected: PASS (all tests, including the updated help-topic test and the 3 new tab tests)

- [ ] **Step 5: Run the full frontend test suite for regressions**

Run: `npx vitest run src/searchRegistry.test.ts src/components/HeaderSearch.test.tsx`
Expected: PASS (both files, all tests)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/HeaderSearch.tsx frontend/src/components/HeaderSearch.test.tsx
git commit -m "feat: surface searchable tabs in header search, prefix help results with category"
```

---

### Task 3: Manual verification in the browser

**Files:** none (verification only).

- [ ] **Step 1: Start the dev stack**

Ensure the dev server is running (`.\dev.ps1` from the repo root, or confirm it's already up), logged in as an admin user.

- [ ] **Step 2: Verify a tab result navigates correctly**

Open the header search (click the search icon or Ctrl/Cmd+K), type "קודי הזמנה" (invite codes). Confirm a result labeled "הגדרות מערכת > קודי הזמנה" appears under a "לשונית" group. Click it. Confirm the browser lands on `/admin/settings?tab=1` with the invite-codes tab actually showing (not the default system-settings tab).

- [ ] **Step 3: Verify role gating**

Log in as (or switch to) a plain soldier account. Search "קודי הזמנה" again. Confirm no result appears (admin-only tab hidden).

- [ ] **Step 4: Verify a non-admin tab**

As the plain soldier, search "מרקטפלייס" (Swaps board tab). Confirm a result labeled "החלפות > מרקטפלייס" appears, and selecting it navigates to `/swaps?tab=board` with the board tab showing.

- [ ] **Step 5: Verify the help-topic prefix**

Search "אלגוריתם". Confirm the existing help-topic result now shows as "עזרה > ⚙️ האלגוריתם" (prefixed), and selecting it still opens the Help modal on the algorithm topic (not a page navigation).

---

## Self-Review

**Spec coverage:**
- 12 tab entries across the 4 in-scope pages, default tabs excluded — Task 1. ✓
- `canAccess` reuses parent page's existing predicate — Task 1 (`isAdmin`, `canApprove`, `authenticated` reused directly, no new predicates written). ✓
- New i18n keys (`search.categories.tab`, `search.tabs.transparency_sub_units`) — Task 1. ✓
- `"PageName > TabName"` label rendering, `?tab=` navigation, new Fuse index, new result group — Task 2. ✓
- Help-topic results re-prefixed with `"עזרה > "` — Task 2. ✓
- Import Session Review excluded — no task references it. ✓
- No backend changes — no task touches `backend/`. ✓
- Manual verification of navigation, gating, and help-prefix — Task 3. ✓

**Placeholder scan:** No TBD/TODO markers; every step has complete code.

**Type consistency:** `TabEntry` defined once in `searchRegistry.ts` (Task 1) and imported as a type-only import in `HeaderSearch.tsx` (Task 2), matching the existing `PageEntry`/`QuickActionEntry`/`HelpTopicEntry` pattern exactly. `FlatResult`'s `"tab"` variant, `handleSelect`'s `"tab"` case, and `labelFor`'s `"tab"` case all reference the same `entry: TabEntry` shape (`path`, `tabParam`, `pageLabelKey`, `labelKey`) introduced in Task 1.
