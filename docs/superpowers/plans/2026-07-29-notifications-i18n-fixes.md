# Notifications & Copy/Routing Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clarify the description on the admin global "טלגרם מופעל" setting, fill in three missing Hebrew i18n keys that were rendering as raw English-looking keys, replace "פאז" with "שלב" in the algorithm help text, and fix the login flow sometimes redirecting to a blank `/setup/telegram` page.

**Architecture:** All four are small, independent fixes. The "leftover English" bug is not a hardcoded string — it's three `NotificationType` enum values with no matching `he.json` translation key, so i18next falls back to rendering the raw key. The blank-page bug is a route-registration race between an auth-driven redirect guard and a settings-driven conditional route; fixed by decoupling the guard from the route's own conditional registration and adding a catch-all route as a safety net.

**Tech Stack:** React/TypeScript, i18next, React Router (frontend only — no backend changes in this plan).

## Global Constraints

- Hebrew UI strings only for new text — add to `frontend/src/i18n/he.json`.
- Do not remove the existing `telegram.enabled` global setting or `registration.telegram_required` per-soldier flag — both stay; this plan only fixes how the frontend reacts to their combination.
- Run `npm run typecheck` after each frontend change in this plan.

---

## File Structure

- **Modify:** `frontend/src/pages/SystemSettingsPage.tsx` — rewrite the `telegram.enabled` setting's description to lead with its notification-channel effect.
- **Modify:** `frontend/src/i18n/he.json` — add `notifications.type_system_announcement`, `notifications.type_transfer_request_rejected`, `notifications.type_enrollment_fields_edited`.
- **Modify:** `frontend/src/components/HelpModal.tsx` — replace "פאז" with "שלב" at lines 189, 191, 193.
- **Modify:** `frontend/src/App.tsx` — fix `TelegramGate` to account for `telegramEnabled` and its loading state; register `/setup/telegram` unconditionally; add a catch-all route.
- **Test:** `frontend/src/App.test.tsx` (new, for the routing fix — check first whether any existing routing test file exists to extend instead).

---

### Task 1: Clarify the description on the admin global "טלגרם מופעל" (telegram.enabled) setting

**Context:** This item was originally assumed to be about the per-user notification-preference toggle in `ProfilePage.tsx`, but it's actually about the **admin global setting** in `SystemSettingsPage.tsx` (the "טלגרם מופעל" toggle, backed by `telegram.enabled`). Investigation found this setting already HAS a description (`SystemSettingsPage.tsx:232-237`: "כיבוי מסתיר את כל ממשק הטלגרם ומפסיק שליחת התראות דרכו") — but it's framed around hiding UI, not around what the user actually asked for: an explanation that this toggle enables/disables Telegram messages as a notification channel in the system. This task rewrites the description to lead with that framing.

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx:232-237` (the `telegram.enabled` setting definition's `description` field)
- Test: manual (label-only change)

- [ ] **Step 1: Read the current setting definition in full**

Read `frontend/src/pages/SystemSettingsPage.tsx` around lines 225-240 to see the exact current object shape for the `telegram.enabled` setting definition (key, label, description, type), so the replacement string goes in the same field with the same surrounding structure.

- [ ] **Step 2: Rewrite the description**

```tsx
// BEFORE (SystemSettingsPage.tsx:232-237, description field)
description: "כיבוי מסתיר את כל ממשק הטלגרם ומפסיק שליחת התראות דרכו",
```

```tsx
// AFTER
description: "מפעיל או מכבה את שליחת התראות המערכת דרך בוט הטלגרם, בנוסף להתראות באפליקציה ובאימייל. כיבוי גם מסתיר את כל ממשק הטלגרם במערכת.",
```

(Match the exact key/quoting style already used in the surrounding object — this is a string-content change only, not a structural one.)

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, log in as admin, go to System Settings, find the "טלגרם מופעל" toggle, confirm the description now explicitly explains it controls Telegram as a notification channel (not just that it hides UI).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx
git commit -m "fix: clarify that the Telegram global setting controls the notification channel, not just UI visibility"
```

---

### Task 2: Fill in missing notification-type translations

**Files:**
- Modify: `frontend/src/i18n/he.json` (notifications section, near line 1087)
- Test: `frontend/src/i18n/he.test.ts` (new — a lightweight completeness check so this class of bug can't silently recur)

**Interfaces:**
- Consumes: `NotificationType` enum values from `backend/app/db/models.py:955-983` (source of truth for what keys must exist).

- [ ] **Step 1: Write a failing completeness test**

```ts
// frontend/src/i18n/he.test.ts
import { describe, it, expect } from "vitest";
import he from "./he.json";

// Mirrors backend/app/db/models.py NotificationType enum values.
// If a new notification type is added to the backend enum, add it here too —
// this test exists specifically to catch the class of bug where a new enum
// value ships with no matching translation key.
const NOTIFICATION_TYPES = [
  "swap_offer", "swap_accepted", "swap_rejected", "swap_offer_incoming",
  "swap_pending_approval",
  "constraint_pending", "exemption_request_pending", "enrollment_request_received",
  "transfer_request_pending", "transfer_request_rejected",
  "system_announcement", "enrollment_fields_edited",
  // ... remaining enum values — read backend/app/db/models.py:955-983 in full
  // and list every member here exactly, not just the ones known to be missing.
];

describe("he.json notification type coverage", () => {
  it("has a type_<value> translation for every backend NotificationType", () => {
    const missing = NOTIFICATION_TYPES.filter((v) => !(`type_${v}` in he.notifications));
    expect(missing).toEqual([]);
  });
});
```

(This step requires reading the FULL `NotificationType` enum body at `backend/app/db/models.py:955-983` — the investigation named 28 members but only enumerated a subset; the implementer must transcribe every single value exactly before this test is meaningful, otherwise it will pass vacuously.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/i18n/he.test.ts`
Expected: FAIL — `missing` includes `system_announcement`, `transfer_request_rejected`, `enrollment_fields_edited`

- [ ] **Step 3: Add the three missing keys**

In `frontend/src/i18n/he.json`, inside the `"notifications"` object, near line 1087:

```json
"type_transfer_request_rejected": "בקשת העברה נדחתה",
"type_system_announcement": "הודעת מערכת",
"type_enrollment_fields_edited": "פרטי הרשמה עודכנו"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/i18n/he.test.ts`
Expected: PASS

- [ ] **Step 5: Manually verify in the running app**

Start `.\dev.ps1`, go to Profile page's notification preferences grid, scroll to the bottom, confirm the previously English-looking rows now show Hebrew labels.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/i18n/he.json frontend/src/i18n/he.test.ts
git commit -m "fix: add missing Hebrew translations for 3 notification types"
```

---

### Task 3: Replace "פאז" with "שלב" in algorithm help text

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx:189, 191, 193`
- Test: manual (copy-only change)

- [ ] **Step 1: Confirm no other occurrences exist**

Run a repo-wide search (Grep tool, pattern `פאז`) to confirm `HelpModal.tsx` is the only file, per investigation.

- [ ] **Step 2: Replace all three occurrences**

```tsx
// BEFORE
189:  <FlowStep icon="0️⃣" text="פאז 0: ניסיון לכסות את כל הרכיב בבת אחת" color="blue" />
191:  <FlowStep icon="1️⃣" text="פאז 1: חיילים ממוינים לפי עומס, נפתרים קבוצה-קבוצה" color="indigo" />
193:  <FlowStep icon="2️⃣" text="פאז 2: כל החיילים — כיסוי רך על מה שנשאר" color="indigo" />
```

```tsx
// AFTER
189:  <FlowStep icon="0️⃣" text="שלב 0: ניסיון לכסות את כל הרכיב בבת אחת" color="blue" />
191:  <FlowStep icon="1️⃣" text="שלב 1: חיילים ממוינים לפי עומס, נפתרים קבוצה-קבוצה" color="indigo" />
193:  <FlowStep icon="2️⃣" text="שלב 2: כל החיילים — כיסוי רך על מה שנשאר" color="indigo" />
```

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, open the help modal, go to the algorithm tab, confirm "שלב 0/1/2" now appears instead of "פאז 0/1/2".

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "fix: use שלב instead of פאז (phase) in algorithm help text"
```

---

### Task 4: Fix blank `/setup/telegram` page after login

**Files:**
- Modify: `frontend/src/App.tsx:47-51, 58-59, 76-78`
- Test: `frontend/src/App.test.tsx` (new)

**Interfaces:**
- Consumes: `usePublicSettings()` from `frontend/src/hooks/usePublicSettings.ts` (returns `SettingsMap | null`, `null` while loading), `useAuth()`'s `telegramRequired`/`telegramLinked` from `frontend/src/auth/AuthContext.tsx`.

- [ ] **Step 1: Write the failing test**

Check whether a routing test harness already exists (search for `MemoryRouter` usage in any `.test.tsx` file) to match conventions. Add:

```tsx
// frontend/src/App.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock hooks — match existing mocking conventions found in the codebase for
// useAuth/usePublicSettings (check an existing test file that mocks these,
// e.g. one under frontend/src/pages/*.test.tsx, before finalizing this mock shape).
vi.mock("./auth/AuthContext", () => ({
  useAuth: () => ({ telegramRequired: true, telegramLinked: false, loggedIn: true, authLoading: false }),
}));
vi.mock("./hooks/usePublicSettings", () => ({
  usePublicSettings: () => null, // simulates settings still loading
}));

import App from "./App";

describe("TelegramGate routing", () => {
  it("does not render a blank page when settings are still loading and telegramRequired is true", () => {
    render(<MemoryRouter initialEntries={["/setup/telegram"]}><App /></MemoryRouter>);
    // Should render either the TelegramSetupPage content or a loading state — never an empty <Outlet/>.
    expect(document.body.textContent).not.toBe("");
  });
});
```

(Adjust the mock shapes to match the real `useAuth`/`usePublicSettings` return shapes and this repo's actual test-rendering conventions for `App.tsx` — it may need additional provider wrappers, e.g. a `QueryClientProvider`; check how other full-app-level tests, if any exist, set up their render tree.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL — blank body / no matching route content

- [ ] **Step 3: Register `/setup/telegram` unconditionally**

In `frontend/src/App.tsx` around lines 76-78:

```tsx
// BEFORE
{telegramEnabled && (
  <Route path="/setup/telegram" element={<TelegramSetupPage />} />
)}
```

```tsx
// AFTER
<Route path="/setup/telegram" element={<TelegramSetupPage />} />
```

(`TelegramSetupPage` itself was confirmed by investigation to render fine standalone — it doesn't depend on `telegramEnabled` internally.)

- [ ] **Step 4: Make `TelegramGate` wait for settings to load and respect `telegramEnabled`**

In `frontend/src/App.tsx` lines 47-51:

```tsx
// BEFORE
function TelegramGate({ children }: { children: ReactElement }) {
  const { telegramRequired, telegramLinked } = useAuth();
  if (telegramRequired && !telegramLinked) return <Navigate to="/setup/telegram" replace />;
  return children;
}
```

```tsx
// AFTER
function TelegramGate({ children }: { children: ReactElement }) {
  const { telegramRequired, telegramLinked } = useAuth();
  const settings = usePublicSettings();
  const settingsLoaded = settings !== null;
  const telegramEnabled = settings?.["telegram.enabled"] === true;

  // Wait for the global setting to load before deciding whether to redirect,
  // so we never redirect into a route that turns out not to apply.
  if (!settingsLoaded) return children;
  if (telegramEnabled && telegramRequired && !telegramLinked) return <Navigate to="/setup/telegram" replace />;
  return children;
}
```

(`usePublicSettings()` is already called once in `App.tsx` near line 58-59 to compute `telegramEnabled` for the route registration — since it's backed by a module-level cache per `usePublicSettings.ts:9-10`, calling it again inside `TelegramGate` is cheap/idempotent, not a duplicate fetch; confirm this by reading `usePublicSettings.ts` in full before assuming, and if it is NOT safely cacheable, thread `telegramEnabled` down as a prop to `TelegramGate` instead of calling the hook a second time.)

- [ ] **Step 5: Add a catch-all route as a safety net**

In `frontend/src/App.tsx`, in the same `<Routes>` block, add as the last route:

```tsx
<Route path="*" element={<Navigate to="/" replace />} />
```

(Place this appropriately relative to the existing route nesting — if routes are split across a protected/unprotected boundary via `ProtectedRoute`, add the catch-all inside the protected block so unauthenticated users still get redirected to login by the existing `ProtectedRoute` logic, not straight to `/`. Read the surrounding route structure at `App.tsx:67-115` first to place it correctly.)

- [ ] **Step 6: Fix the same race in RegisterPage.tsx**

`frontend/src/pages/RegisterPage.tsx:138` calls `navigate("/setup/telegram", { replace: true })` after registration — since the route is now registered unconditionally (Step 3), this no longer risks hitting a missing route, but confirm the navigation still only happens when telegram setup is actually relevant (i.e. this call site should itself check `telegramEnabled`/`telegramRequired` before navigating there, rather than always redirecting — read the surrounding code at that line to confirm existing conditionals are still correct given Step 3's change, since removing the route's own gate means this call site is now the only place preventing an unnecessary redirect for users who don't need Telegram setup).

- [ ] **Step 7: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS

- [ ] **Step 8: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors

- [ ] **Step 9: Manually verify in the running app**

Start `.\dev.ps1`. With `telegram.enabled=true` and a test soldier that has `telegramRequired=true`/`telegramLinked=false`, log in and confirm you land on a properly-rendered `/setup/telegram` page (not blank), including on a fast/throttled network (use browser devtools network throttling to make the settings fetch slow, confirming no blank-page flash). Also confirm navigating to a nonsense URL like `/does-not-exist` redirects sensibly instead of blanking.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/pages/RegisterPage.tsx
git commit -m "fix: stop redirecting to a blank /setup/telegram page during a settings-load race"
```

---

## Self-Review Notes

- All 4 spec items (Telegram toggle description, leftover English strings, פאז→שלב, blank /setup/telegram page) are covered by Tasks 1-4.
- Task 1 was retargeted after clarification: it's the admin global "telegram.enabled" setting in SystemSettingsPage.tsx, not the per-user ProfilePage preference toggle — the latter already correctly has no separate ask here.
- Task 2 adds a regression-preventing completeness test rather than just patching the 3 known-missing keys, since the root cause (enum values without matching i18n keys) can recur silently.
- Task 4 fixes the root cause (gate doesn't account for settings-loading state or the enabled flag) plus adds a catch-all safety net, rather than only patching the specific observed symptom.
- No placeholders; all steps have concrete code and exact commands, with a few "read the file first" notes only where exact enum membership or existing test conventions must be transcribed precisely rather than guessed.
