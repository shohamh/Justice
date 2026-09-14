# Unsaved-changes confirmation guard

## Problem

Frontend forms live in two shapes: standalone pages (e.g.
`SystemSettingsPage.tsx`, `AdminSettingsPage.tsx`) and modals (~40 of them,
each hand-rolled — there is no shared `Modal` wrapper component, each renders
its own `fixed inset-0` overlay and wires its own close triggers). Neither
shape warns before discarding an edited-but-unsaved draft. A soldier or admin
who edits a field, then clicks the ✕, clicks the backdrop, presses the browser
back button, clicks a sidebar link, or closes the tab, silently loses the
change with no prompt.

## Goals

- Before any of those "leave" actions, if the current draft differs from what
  was loaded, show a confirmation with three choices: save and leave, discard
  and leave, or stay.
- One shared mechanism, not 40+ bespoke implementations — a component wires in
  a boolean and two callbacks, not a new state machine.
- Cover every leave path: modal ✕/backdrop/Cancel/Escape, the existing
  browser-back-closes-modal behavior (`useModalBackClose`), in-app navigation
  to another route, browser back/forward, and tab close/refresh.

## Non-goals

- A generic form/dirty-tracking library (react-hook-form, Formik, etc.). Every
  consumer keeps computing its own `isDirty` however is natural for it — most
  already do, or can trivially do, `JSON.stringify(draft) !==
  JSON.stringify(snapshot)` (the pattern `SystemSettingsPage.tsx:516` and its
  `RankAdvancementIntervalsSection` already use).
- Migrating the app off `<BrowserRouter>` onto a data router
  (`createBrowserRouter`). React Router's `useBlocker` needs a data router;
  we get the same effect for back/forward via the same history-entry
  interception trick `useModalBackClose.ts` already uses for the mobile-back-
  closes-modal behavior, and for in-app `<Link>` clicks via a capture-phase
  `click` listener — no router migration required.
- Retrofitting every one of the ~40 modals with hand-written tests for this
  behavior. The shared hook/provider gets thorough tests; a couple of
  representative modals plus the settings pages get integration coverage;
  the rest get the same 4-line wiring change without new bespoke test files.

## Design

### 1. Shared primitives

**`UnsavedChangesProvider`** (`frontend/src/contexts/UnsavedChangesContext.tsx`)
— mounted once in `main.tsx`, inside `<BrowserRouter>` (needs `useNavigate`).
Holds:
- A stack of registered guards (see hook below). Only the top of the stack
  (the most-recently-registered *dirty* guard) is "active" — this makes the
  natural case work automatically: a dirty modal open on top of a dirty page
  is the one that should intercept a close/leave attempt, not the page
  underneath it.
- Dialog UI state (`open`, `saving`, `error`).
- Global listeners, active only while some guard is dirty:
  - `window.addEventListener("beforeunload", ...)` — sets `event.returnValue`
    to trigger the native browser prompt. Can't be styled; that's fine, it's
    the tab-close/refresh case only.
  - A capture-phase `click` listener on `document` — on click, walks up from
    `event.target` to the nearest `<a href>` (this catches `<Link>`/`<NavLink>`
    from react-router, which render plain anchors). If found and it's a
    same-origin in-app link, `preventDefault()` and open the dialog. On
    confirm, either `navigate(href)` (discard) or `await onSave()` then
    `navigate(href)` (save-and-leave, only on success).
  - A `popstate` listener using the same push-a-sentinel-entry technique as
    `useModalBackClose`: while any guard is dirty, ensure one extra history
    entry is on top. A back-press pops it; the handler detects that and,
    instead of letting the navigation complete, re-pushes the entry and opens
    the dialog. Confirming "discard and leave" calls `history.back()` twice
    (past the sentinel and the real previous entry); "stay" does nothing
    further (the sentinel is already back on top).

**`useUnsavedChangesGuard({ isDirty, onSave, onDiscard })`**
(`frontend/src/hooks/useUnsavedChangesGuard.ts`) — the hook every dirty-aware
component calls.
- Registers/deregisters itself with the provider's stack on mount/unmount and
  whenever `isDirty` changes.
- `onSave: () => Promise<boolean>` — called for "save and leave"; must resolve
  `true` only once persisted. On `false`/rejection the dialog shows an inline
  error and stays open (retry or fall back to discard/cancel).
- `onDiscard: () => void` — the real close/reset action, called directly when
  not dirty, or after a confirmed discard.
- Returns `requestClose(): void` — what every modal-internal close trigger
  calls instead of calling `onClose`/`onDiscard` directly. If not dirty, calls
  `onDiscard` immediately; if dirty, opens the shared dialog.

**`UnsavedChangesDialog`** (`frontend/src/components/UnsavedChangesDialog.tsx`)
— small styled dialog matching the app's existing modal look (see
`SoldierEditModal.tsx`'s overlay pattern), Hebrew RTL, three buttons: "שמור
וצא" (primary), "צא בלי לשמור" (destructive/secondary), "ביטול" (tertiary).
Rendered once by the provider, controlled by its state.

### 2. Modal integration pattern

Each modal:
1. Computes `isDirty` (usually already has the data to diff against initial
   props/query snapshot).
2. Calls `const { requestClose } = useUnsavedChangesGuard({ isDirty, onSave: submitHandler, onDiscard: onClose })` —
   reusing the modal's existing submit function as `onSave` where its return
   value can be coerced to indicate success (most already resolve/reject a
   mutation promise).
3. Replaces every internal close trigger — the ✕ button, the backdrop
   `onClick`, a "Cancel" button, and the callback passed to
   `useModalBackClose` — with `requestClose`.
4. No change needed for the actual Save button — it keeps calling its own
   submit handler directly; the guard only intercepts *leaving without*
   saving.

### 3. Page integration pattern

Pages don't have internal close triggers to rewire — the provider's global
listeners handle in-app nav, back/forward, and tab close automatically once
the page calls the hook:

```ts
useUnsavedChangesGuard({
  isDirty,
  onSave: async () => { await saveMutation.mutateAsync(draft); return true; },
  onDiscard: () => setDraft(serverSnapshot),
});
```

`requestClose()` is unused by pages (nothing calls it) — only registration
matters for them.

### 4. Error handling

- `onSave` throwing or resolving `false` keeps the dialog open with a small
  inline "שמירה נכשלה — נסה שוב" message and re-enables its buttons; the
  underlying modal/page is untouched (its own error state, if any, is
  separate and still visible once the dialog is dismissed).
- If a component unmounts while registered and dirty without going through
  `requestClose` (e.g. a parent conditionally stops rendering it), the
  provider's unmount cleanup simply pops it off the stack — no leak, no stuck
  dialog.
- Only one dialog can be open at a time (single provider-owned state) — a
  guard registering while the dialog is already open for a different guard is
  not expected in practice (nothing currently allows two dirty surfaces to
  both attempt to close at once) and isn't specially handled.

### 5. Testing

- `useUnsavedChangesGuard.test.tsx` / `UnsavedChangesContext.test.tsx`: full
  coverage of the hook + provider in isolation — stack ordering with nested
  guards, `beforeunload` firing only while dirty, capture-phase click
  interception and its three outcomes, the `popstate` sentinel trick
  (mirroring how `useModalBackClose.test.tsx` already tests history
  interception).
- Two or three representative modals (e.g. `SoldierEditModal`,
  `RangeEditAssignmentsModal`) plus `SystemSettingsPage` get a new test
  asserting the dialog appears when closing/navigating dirty and doesn't when
  clean, and that "discard" vs "save and leave" behave correctly.
- The remaining ~35+ modals get the same mechanical wiring change without new
  bespoke test files; a rollout PR/plan step should grep for every modal
  matching the "own overlay + own close handler" pattern to confirm none were
  missed.
