# Ranges UI Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ranges planning page, detail modal, edit form, and assignment editor visually and behaviorally consistent with shift management.

**Architecture:** Keep range-specific API and authorization semantics, but move presentation onto the existing `PlanningTable`, `DataTable`, `EventDetailModal`, `AssignmentRow`, and shift-style modal/footer patterns. Add one range-specific assignment editor that maps the existing range API to the shift editor interaction model.

**Tech Stack:** React 18, TypeScript, TanStack Query, Testing Library, Vitest, Tailwind classes, existing FastAPI range API.

## Global Constraints

- Preserve range-specific workflows: instructions, contact, primary/reserve assignments, drafts, auto-assignment, attendance/no-show, excusal, cancel, and delete.
- Do not copy the shift assignment domain model into ranges; reuse visual and interaction primitives only where semantics match.
- Preserve `canPlan`/backend authorization and commander read-only behavior.
- Keep explicit action buttons separate from row selection.
- Run focused range tests, then `npm run typecheck`, `npm run lint`, and the complete frontend suite.

---

### Task 1: Shared planning controls and range table parity

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/components/ranges/RangePlanningTable.tsx`
- Modify: `frontend/src/components/planning/PlanningTable.tsx` only if a small reusable control is missing
- Test: `frontend/src/pages/RangesPage.test.tsx`
- Test: `frontend/src/components/ranges/RangePlanningTable.test.tsx` (create if needed)

**Interfaces:**
- Consumes: `RangeEvent`, `PlanningTable`, `DataTable`, `queryKeys.ranges()`.
- Produces: a range page with the same header/filter/table/button treatment as `ShiftsManagementPage`.

- [ ] **Step 1: Add failing UI assertions** for the range page header, filter control classes/labels, row action hierarchy, and explicit location action. Assert that selecting a filter updates the visible rows and that row actions do not trigger row selection.

- [ ] **Step 2: Run the focused tests**

Run from `frontend/`:

```powershell
npm test -- --run src/pages/RangesPage.test.tsx src/components/ranges/RangePlanningTable.test.tsx
```

Expected: the new parity assertions fail against the current bespoke controls.

- [ ] **Step 3: Implement the table/page parity**

Use the same Tailwind class vocabulary and control grouping as `ShiftsManagementPage` and `PlanningTable`. Keep range-specific filters (date from/to, type, status, fill) but render them in the shared toolbar shape. Move action labels into consistent button styles and use the existing table's search/filter placeholder and empty state. Ensure delete uses derived filled counts rather than optional API fields directly.

- [ ] **Step 4: Re-run focused tests**

```powershell
npm test -- --run src/pages/RangesPage.test.tsx src/components/ranges/RangePlanningTable.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/pages/RangesPage.tsx frontend/src/components/ranges/RangePlanningTable.tsx frontend/src/pages/RangesPage.test.tsx frontend/src/components/ranges/RangePlanningTable.test.tsx
git commit -m "refactor: align range planning controls with shifts"
```

### Task 2: Detail and edit modal visual parity

**Files:**
- Modify: `frontend/src/components/ranges/RangeFormModal.tsx`
- Modify: `frontend/src/components/ranges/RangeDetailContent.tsx`
- Modify: `frontend/src/pages/RangesPage.tsx`
- Test: `frontend/src/components/ranges/RangeFormModal.test.tsx`
- Test: `frontend/src/pages/RangesPage.test.tsx`

**Interfaces:**
- Consumes: `EventDetailModal`, `ShiftFormModal` layout conventions, `RangeEvent`, existing range mutation callbacks.
- Produces: consistent range detail and edit modals without changing API payload semantics.

- [ ] **Step 1: Add failing modal assertions** for standard modal header/footer structure, grouped field sections, consistent Save/Cancel buttons, metadata/action layout, and visible instructions/contact/notes.

- [ ] **Step 2: Run the focused modal tests**

```powershell
npm test -- --run src/components/ranges/RangeFormModal.test.tsx src/pages/RangesPage.test.tsx
```

Expected: the new structural/style-hook assertions fail.

- [ ] **Step 3: Restyle and reorganize `RangeFormModal`**

Follow `ShiftFormModal`'s modal container, form spacing, responsive grid, section labels, and footer button classes. Keep existing validation, nullable optional fields, `force_schedule_change`, and pending behavior. Add stable test IDs only where semantic roles are insufficient.

- [ ] **Step 4: Restyle `RangeDetailContent` and page actions**

Use the standard modal metadata/action treatment. Keep roster, attendance, excusal, and draft controls but group them into visually distinct sections. Replace inline unstyled controls with the same button variants used by shift management, including disabled/pending and danger states.

- [ ] **Step 5: Run focused tests and commit**

```powershell
npm test -- --run src/components/ranges/RangeFormModal.test.tsx src/pages/RangesPage.test.tsx
git add frontend/src/components/ranges/RangeFormModal.tsx frontend/src/components/ranges/RangeDetailContent.tsx frontend/src/pages/RangesPage.tsx frontend/src/components/ranges/RangeFormModal.test.tsx frontend/src/pages/RangesPage.test.tsx
git commit -m "refactor: align range modals with shift dialogs"
```

Expected: focused tests PASS before commit.

### Task 3: Shift-style range assignment editor

**Files:**
- Create: `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx`
- Create: `frontend/src/components/ranges/RangeEditAssignmentsModal.test.tsx`
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/components/ranges/RangeDetailContent.tsx`
- Modify: `frontend/src/api/ranges.ts` only if a typed wrapper is missing

**Interfaces:**
- Consumes: `RangeEvent`, `RangeAssignment`, `addRangeAssignment`, `removeRangeAssignment`, `autoAssignRange`, `confirmDraftAssignment`, `confirmAllDrafts`, `listSoldiers`.
- Produces: `RangeEditAssignmentsModal` props:

```ts
interface RangeEditAssignmentsModalProps {
  open: boolean;
  event: RangeEvent;
  soldiers: SoldierDTO[];
  canManage: boolean;
  onClose: () => void;
  onChanged: () => Promise<void>;
}
```

- [ ] **Step 1: Add failing component tests** covering primary/reserve sections, existing draft badge, add soldier, reserve toggle, remove pending state, auto-assign, confirm draft/all, full-capacity messaging, and close behavior.

- [ ] **Step 2: Run the new test file**

```powershell
npm test -- --run src/components/ranges/RangeEditAssignmentsModal.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the modal**

Model the structure and interaction density after `ShiftEditAssignmentsModal`: standard modal shell, current assignment tables/rows, separate primary and reserve controls, searchable soldier picker, per-action pending state, and footer actions. Use range API calls and invalidate via `onChanged`; do not introduce shift candidate endpoints or shift-specific eligibility rules.

- [ ] **Step 4: Integrate from the detail modal**

Add an explicit “edit assignments” action visible only to planners for planned events. Keep attendance/no-show and soldier excusal in the detail view. Ensure opening/closing does not change selected event and that query data refreshes after mutations.

- [ ] **Step 5: Run assignment tests and commit**

```powershell
npm test -- --run src/components/ranges/RangeEditAssignmentsModal.test.tsx src/pages/RangesPage.test.tsx
git add frontend/src/components/ranges/RangeEditAssignmentsModal.tsx frontend/src/components/ranges/RangeEditAssignmentsModal.test.tsx frontend/src/components/ranges/RangeDetailContent.tsx frontend/src/pages/RangesPage.tsx frontend/src/api/ranges.ts
git commit -m "feat: add shift-style range assignment editor"
```

### Task 4: Integration, accessibility, and full verification

**Files:**
- Modify: any files from Tasks 1–3 that need integration fixes
- Test: relevant range tests and complete frontend suite

**Interfaces:**
- Consumes: all completed range parity components.
- Produces: verified UI parity with no backend changes unless a shared contract regression is found.

- [ ] **Step 1: Run focused range tests**

```powershell
npm test -- --run src/pages/RangesPage.test.tsx src/components/ranges/RangeFormModal.test.tsx src/components/ranges/RangeEditAssignmentsModal.test.tsx src/components/ranges/RangeAttendancePanel.test.tsx
```

- [ ] **Step 2: Run typecheck and lint**

```powershell
npm run typecheck
npm run lint
```

- [ ] **Step 3: Run the complete frontend suite**

```powershell
npm test -- --run
```

Expected: all existing tests and new range parity tests pass.

- [ ] **Step 4: Review the final diff**

Check that no range API/authorization behavior was unintentionally changed, no duplicate shift-domain logic was introduced, and all new buttons have semantic labels, disabled states, and test coverage.

- [ ] **Step 5: Commit integration fixes**

```powershell
git add frontend/src
git commit -m "test: verify ranges UI parity"
```
