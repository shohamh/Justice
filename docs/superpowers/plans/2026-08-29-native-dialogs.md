# Native Browser Dialog Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every runtime frontend `alert()`, `confirm()`, and `prompt()` call with translated, RTL-aware application modals.

**Architecture:** Add shared confirmation, message, and text-input dialog components on top of `EventDetailModal`, then migrate existing handlers from synchronous browser calls to local modal state and callbacks. Preserve each handler's current authorization, async operation, error handling, and cancellation semantics.

**Tech Stack:** React, TypeScript, react-i18next, Vitest, Testing Library, Tailwind CSS.

**Spec:** `docs/superpowers/specs/2026-08-29-native-dialogs-design.md`

## Global Constraints

- Do not change backend APIs or business rules.
- All visible dialog text must use i18n keys with Hebrew translations.
- Do not mutate data until the user confirms.
- Preserve existing async loading, error handling, permission checks, and danger styling.
- Reuse `EventDetailModal` and `useModalBackClose`.
- Preserve unrelated dirty work, especially the current `HierarchyTree` changes.

---

### Task 1: Shared dialog primitives

**Files:**
- Create: `frontend/src/components/ConfirmDialog.tsx`
- Create: `frontend/src/components/MessageDialog.tsx`
- Create: `frontend/src/components/InputDialog.tsx`
- Modify: `frontend/src/components/ranges/ConfirmDialog.tsx` to re-export or delegate to the shared confirmation component
- Test: `frontend/src/components/ConfirmDialog.test.tsx`
- Test: `frontend/src/components/MessageDialog.test.tsx`
- Test: `frontend/src/components/InputDialog.test.tsx`

**Interfaces:**

- `ConfirmDialogProps = { open: boolean; title: ReactNode; message: ReactNode; confirmLabel?: string; cancelLabel?: string; danger?: boolean; onConfirm: () => void; onClose: () => void }`
- `MessageDialogProps = { open: boolean; title: ReactNode; message: ReactNode; closeLabel?: string; onClose: () => void }`
- `InputDialogProps = { open: boolean; title: ReactNode; message?: ReactNode; label: string; initialValue?: string; placeholder?: string; multiline?: boolean; confirmLabel?: string; cancelLabel?: string; required?: boolean; onConfirm: (value: string) => void; onClose: () => void }`

- [ ] **Step 1: Write failing shared-dialog tests**

Test public behavior with `render`, `fireEvent`, and `screen`: confirmation cancel does not invoke `onConfirm), confirmation invokes it once, message invokes only `onClose), input submits the trimmed value, input cancel submits nothing, and required input disables confirmation while blank. Assert Hebrew fallback labels and `danger` styling.

- [ ] **Step 2: Run the tests and verify they fail**

Run from `frontend`:

```
npx vitest run src/components/ConfirmDialog.test.tsx src/components/MessageDialog.test.tsx src/components/InputDialog.test.tsx
```

Expected: FAIL because the shared components do not exist.

- [ ] **Step 3: Implement the shared dialogs**

Render each dialog through `EventDetailModal`. Keep state reset on close. Use translated defaults `common.confirm`, `common.cancel`, and `common.close` with Hebrew fallbacks. The input dialog must call `onConfirm(value.trim())` only when required validation passes.

- [ ] **Step 4: Run the tests and verify they pass**

```
npx vitest run src/components/ConfirmDialog.test.tsx src/components/MessageDialog.test.tsx src/components/InputDialog.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Add the shared Hebrew translations**

Add generic dialog labels and any missing operation-specific dialog keys to `frontend/src/i18n/he.json`; keep dynamic messages interpolated by react-i18next.

- [ ] **Step 6: Commit**

```
git add frontend/src/components/ConfirmDialog.tsx frontend/src/components/MessageDialog.tsx frontend/src/components/InputDialog.tsx frontend/src/components/ranges/ConfirmDialog.tsx frontend/src/components/*Dialog.test.tsx frontend/src/i18n/he.json
git commit -m "feat: add translated application dialogs"
```

### Task 2: Hierarchy and soldier flows

**Files:**
- Modify: `frontend/src/components/HierarchyTree.tsx`
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx`
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx`
- Modify: `frontend/src/contexts/SoldierModalContext.tsx`
- Modify: `frontend/src/components/EditNodeDialog.tsx`
- Modify: `frontend/src/components/HierarchyTree.test.tsx`
- Modify: `frontend/src/pages/TeamHierarchyPage.test.tsx`

**Interfaces:**

- Each component owns modal state for its action and passes a callback to the shared dialog.
- Existing action handlers remain the mutation boundary; dialog confirmation calls those handlers.

- [ ] **Step 1: Add failing tests for hierarchy deletion and reset-password confirmation**

Render the relevant component, click the trash/reset action, assert no native dialog is called, assert the application dialog appears in Hebrew, click cancel and assert no mutation, then click confirm and assert the original API call.

- [ ] **Step 2: Run focused tests and verify they fail**

```
npx vitest run src/components/HierarchyTree.test.tsx src/pages/TeamHierarchyPage.test.tsx
```

Expected: FAIL because handlers still call native dialogs.

- [ ] **Step 3: Migrate the confirm and alert calls**

Replace hierarchy deletion and reset-password `confirm` calls with `ConfirmDialog`. Replace hierarchy error alerts and soldier-loading failure alerts with `MessageDialog`. Keep commander-protection messages as message dialogs and preserve their early-return behavior. Do not alter the uncommitted hierarchy logic unrelated to dialog presentation.

- [ ] **Step 4: Migrate constraint-rejection prompts**

Replace `UnifiedSoldierModal`'s rejection prompt with `InputDialog`, retaining the existing distinction between cancel (`null`) and submitting an empty note.

- [ ] **Step 5: Run focused tests and verify they pass**

```
npx vitest run src/components/HierarchyTree.test.tsx src/pages/TeamHierarchyPage.test.tsx src/components/UnifiedSoldierModal.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```
git add frontend/src/components/HierarchyTree.tsx frontend/src/pages/TeamHierarchyPage.tsx frontend/src/components/UnifiedSoldierModal.tsx frontend/src/contexts/SoldierModalContext.tsx frontend/src/components/EditNodeDialog.tsx frontend/src/components/HierarchyTree.test.tsx frontend/src/pages/TeamHierarchyPage.test.tsx
git commit -m "fix: replace native hierarchy dialogs"
```

### Task 3: Ranges and shifts

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/components/ranges/RangeLocationsContent.tsx`
- Modify: `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx`
- Modify: `frontend/src/pages/ShiftsPage.tsx`
- Modify: `frontend/src/components/ShiftAssignModal.tsx`
- Modify: `frontend/src/components/ranges/ConfirmDialog.tsx` if compatibility cleanup is required
- Test: corresponding existing `RangesPage`, range-modal, `RangeLocationsContent`, `ShiftsPage`, and `ShiftAssignModal` tests

**Interfaces:**

- Confirmation callbacks invoke the existing delete/clear/cancel/assign operations.
- Reason prompts use `InputDialog` and pass the same trimmed reason to existing APIs.

- [ ] **Step 1: Add failing tests for range location deletion and assignment-removal prompt**

Assert the styled dialog appears, native browser APIs are untouched, cancel preserves the row, and confirm submits the existing mutation/reason.

- [ ] **Step 2: Implement range migrations**

Convert range location deletion to `ConfirmDialog`. Convert assignment-removal reason collection to `InputDialog`. Keep existing `OverrideReasonModal` behavior separate because it already has domain-specific validation.

- [ ] **Step 3: Add failing tests for shifts**

Cover single and bulk clear/delete/cancel operations, the no-deletable-items message, and the permanent-delete danger variant. Verify dynamic counts render in Hebrew and only confirmed actions call APIs.

- [ ] **Step 4: Implement shift migrations**

Replace every native shift `confirm` with stateful `ConfirmDialog`; replace validation/error `alert` calls with `MessageDialog`. Preserve preview data and the existing reason prompt semantics if any flow requires text input.

- [ ] **Step 5: Migrate assignment eligibility confirmation**

Replace `ShiftAssignModal`'s native confirmation with `ConfirmDialog`, retaining the current warning message and API call only after confirmation.

- [ ] **Step 6: Run focused tests and verify they pass**

```
npx vitest run src/pages/RangesPage.test.tsx src/components/ranges/RangeEditAssignmentsModal.test.tsx src/components/ranges/RangeLocationsContent.test.tsx src/pages/ShiftsPage.test.tsx src/components/ShiftAssignModal.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```
git add frontend/src/pages/RangesPage.tsx frontend/src/components/ranges/RangeLocationsContent.tsx frontend/src/components/ranges/RangeEditAssignmentsModal.tsx frontend/src/pages/ShiftsPage.tsx frontend/src/components/ShiftAssignModal.tsx frontend/src/components/ranges/*test.tsx frontend/src/pages/*test.tsx
git commit -m "fix: replace native range and shift dialogs"
```

### Task 4: Imports, duties, algorithm, deputies, requests, and remaining flows

**Files:**
- Modify: `frontend/src/pages/ImportSessionsListPage.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Modify: `frontend/src/pages/DutyManagementPage.tsx`
- Modify: `frontend/src/components/DutyHistoryPanel.tsx`
- Modify: `frontend/src/components/AlgorithmProposalTable.tsx`
- Modify: `frontend/src/pages/ShiftTemplatesPage.tsx`
- Modify: `frontend/src/components/DeputiesPanel.tsx`
- Modify: `frontend/src/pages/MyRequestsPage.tsx`
- Modify: `frontend/src/components/UpcomingSnapshot.tsx`
- Modify: `frontend/src/pages/ProfilePage.tsx`
- Modify: `frontend/src/components/AssignDutyManagersDialog.tsx`
- Modify: `frontend/src/components/DutyManagerPortfolioDialog.tsx`
- Create: `frontend/src/pages/ImportSessionsListPage.test.tsx` if the current page has no focused test file
- Create: `frontend/src/components/AlgorithmProposalTable.test.tsx` if the current component has no focused test file
- Create: `frontend/src/pages/ShiftTemplatesPage.test.tsx` if the current page has no focused test file
- Update: corresponding existing tests for each flow

**Interfaces:**

- Confirm callbacks preserve each original operation and dynamic message.
- Message dialogs replace operation/validation alerts.
- Input dialogs replace duty cancel/override/replacement prompts and history decision-note prompts.

- [ ] **Step 1: Add failing tests for one representative flow in each group**

Cover import draft cancellation, duty draft cancellation with reason, algorithm draft cancellation, deputy revocation, request cancellation, upcoming soldier action, and operation-error message rendering. Assert Hebrew dialog copy and no native API calls.

- [ ] **Step 2: Implement import and duty dialog state**

Use `ConfirmDialog`, `MessageDialog`, and `InputDialog` while preserving sequential prompt semantics in `DutyManagementPage` by opening the next input only after the previous value is confirmed.

- [ ] **Step 3: Implement algorithm, deputies, requests, and upcoming-action confirmations**

Move each synchronous confirmation into a local callback and keep the existing API call in that callback. Use danger styling for destructive actions.

- [ ] **Step 4: Implement remaining message and input dialogs**

Replace operation-error alerts with `MessageDialog`; replace history decision-note prompts with `InputDialog`. Preserve cancel/empty-note behavior exactly.

- [ ] **Step 5: Run the representative and affected test suites**

```
npx vitest run src/pages/ImportSessionsListPage.test.tsx src/pages/ImportSessionReviewPage.test.tsx src/pages/DutyManagementPage.test.tsx src/components/DutyHistoryPanel.test.tsx src/components/AlgorithmProposalTable.test.tsx src/pages/ShiftTemplatesPage.test.tsx src/components/DeputiesPanel.test.tsx src/pages/MyRequestsPage.test.tsx src/components/UpcomingSnapshot.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```
git add frontend/src/pages frontend/src/components
git commit -m "fix: replace remaining native frontend dialogs"
```

### Task 5: Runtime inventory, full verification, and cleanup

**Files:**
- Modify: any affected tests from Tasks 2-4
- Modify: `frontend/src/i18n/he.json` for missing translation keys discovered during verification

- [ ] **Step 1: Search runtime source for native dialogs**

```
rg -n -i --glob '!**/*.test.*' --glob '!**/docs/**' --glob '!node_modules/**' "window\\.(confirm|alert|prompt)|\\b(confirm|alert|prompt)\\s*\\(" frontend/src
```

Expected: no runtime browser dialog calls. Review any remaining ordinary function names such as `confirmAssignments` manually and retain them when they are not browser APIs.

- [ ] **Step 2: Run frontend verification**

```
npm test -- --run --maxWorkers=1 --no-file-parallelism
npm run typecheck
npm run lint
git diff --check
```

Expected: all commands pass.

- [ ] **Step 3: Review translations and behavior**

Confirm every dialog has Hebrew title/message/button text, dynamic interpolation is readable in RTL, browser back closes only the active dialog, and no API action occurs on cancel.

- [ ] **Step 4: Commit final cleanup**

```
git add frontend/src docs/superpowers/plans/2026-08-29-native-dialogs.md
git commit -m "test: verify styled dialogs replace native browser dialogs"
```
