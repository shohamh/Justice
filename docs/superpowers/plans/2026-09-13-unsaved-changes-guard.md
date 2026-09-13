# Unsaved-Changes Confirmation Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before a modal or settings page discards an unsaved edit (via close button, backdrop, Escape/back-button, in-app navigation, or tab close), show a confirmation offering save-and-leave, discard-and-leave, or stay.

**Architecture:** One `UnsavedChangesProvider` (mounted once in `main.tsx`) holds a stack of registered "guards" and renders one shared confirmation dialog. Every dirty-aware component calls `useUnsavedChangesGuard({ kind, isDirty, onSave, onDiscard })`; modals additionally route every internal close trigger through the hook's returned `requestClose()`. The provider itself intercepts `beforeunload`, in-app `<a>`/`<Link>` clicks, and the browser back/forward buttons (page guards only — modal guards reuse the existing `useModalBackClose` mechanism, routed through `requestClose`).

**Tech Stack:** React 18, TypeScript, react-router-dom v6 (`<BrowserRouter>`, not a data router), Vitest + Testing Library.

**Spec:** [docs/superpowers/specs/2026-09-13-unsaved-changes-guard-design.md](../specs/2026-09-13-unsaved-changes-guard-design.md)

## Global Constraints

- No new dependency — no react-hook-form/Formik, no react-router data-router migration.
- Every consumer keeps computing its own `isDirty` (usually `JSON.stringify(draft) !== JSON.stringify(snapshot)`, already the pattern in `SystemSettingsPage.tsx`).
- Dialog copy is Hebrew, RTL, matching existing modal styling (see `SoldierEditModal.tsx`'s overlay classes).
- `onSave` must resolve `true` only once persisted; `false`/throw keeps the dialog open with an inline retry error.
- A "modal" guard (`kind: "modal"`) never touches history itself — it relies on the modal's existing `useModalBackClose` hook, now pointed at `requestClose` instead of `onClose`. Only a "page" guard (`kind: "page"`) participates in the provider's own back/forward interception. This split avoids two independent systems (the modal's own history entry, and the provider's) fighting over the same back-press.

---

### Task 1: Guard registry + `useUnsavedChangesGuard` hook

**Files:**
- Create: `frontend/src/contexts/UnsavedChangesContext.tsx`
- Create: `frontend/src/hooks/useUnsavedChangesGuard.ts`
- Test: `frontend/src/hooks/useUnsavedChangesGuard.test.tsx`

**Interfaces:**
- Produces: `UnsavedChangesGuardKind = "page" | "modal"`; `UnsavedChangesGuardHandlers { kind, isDirty, onSave: () => Promise<boolean>, onDiscard: () => void }`; `UnsavedChangesContextValue { setGuard(id, handlers), removeGuard(id), requestClose(id), getGuards(): ReadonlyArray<{id:number} & UnsavedChangesGuardHandlers> }`; `UnsavedChangesContext` (React context, default `null`); `useUnsavedChangesGuard(handlers): { requestClose: () => void }`.
- Consumes: nothing from earlier tasks.

This task builds the registry only — no dialog UI, no global listeners yet. `requestClose` when dirty just calls a no-op `onOpenDialog` callback stored on the context (Task 2 fills in the real dialog); for this task, `requestClose` on a dirty guard with no dialog wired up is verified by asserting the context's internal "pending open" request fires, via a test double provider.

To keep Task 1 fully testable in isolation without inventing throwaway internals that Task 2 then discards, `UnsavedChangesContext.tsx` in this task defines the **real** provider shape, but the provider's `requestClose` implementation only stores "which guard wants to open" in state (`pendingDialogGuardId`) — Task 2 adds the actual dialog component that reads that state. This task's test renders the provider directly and asserts on that internal state via a small test-only consumer, so nothing is thrown away.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/hooks/useUnsavedChangesGuard.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { useState } from "react";
import { UnsavedChangesProvider, useUnsavedChangesInternalsForTests } from "../contexts/UnsavedChangesContext";
import { useUnsavedChangesGuard } from "./useUnsavedChangesGuard";

function DirtyPage({ onSave, onDiscard }: { onSave: () => Promise<boolean>; onDiscard: () => void }) {
  const [dirty, setDirty] = useState(false);
  const { requestClose } = useUnsavedChangesGuard({ kind: "page", isDirty: dirty, onSave, onDiscard });
  return (
    <div>
      <button onClick={() => setDirty(true)} data-testid="make-dirty">dirty</button>
      <button onClick={requestClose} data-testid="request-close">close</button>
    </div>
  );
}

function PendingProbe() {
  const { pendingDialogGuardId } = useUnsavedChangesInternalsForTests();
  return <div data-testid="pending">{pendingDialogGuardId ?? "none"}</div>;
}

describe("useUnsavedChangesGuard", () => {
  it("discards immediately when not dirty", () => {
    const onDiscard = vi.fn();
    render(
      <UnsavedChangesProvider>
        <DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />
        <PendingProbe />
      </UnsavedChangesProvider>,
    );
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("pending")).toHaveTextContent("none");
  });

  it("opens the pending dialog state instead of discarding when dirty", () => {
    const onDiscard = vi.fn();
    render(
      <UnsavedChangesProvider>
        <DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />
        <PendingProbe />
      </UnsavedChangesProvider>,
    );
    fireEvent.click(screen.getByTestId("make-dirty"));
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).not.toHaveBeenCalled();
    expect(screen.getByTestId("pending")).not.toHaveTextContent("none");
  });

  it("discards immediately (with a warning) when used outside a provider", () => {
    const onDiscard = vi.fn();
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />);
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    errorSpy.mockRestore();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/hooks/useUnsavedChangesGuard.test.tsx`
Expected: FAIL — `../contexts/UnsavedChangesContext` and `./useUnsavedChangesGuard` don't exist yet.

- [ ] **Step 3: Write the registry + provider**

```tsx
// frontend/src/contexts/UnsavedChangesContext.tsx
import { createContext, ReactNode, useCallback, useContext, useRef, useState } from "react";

export type UnsavedChangesGuardKind = "page" | "modal";

export interface UnsavedChangesGuardHandlers {
  kind: UnsavedChangesGuardKind;
  isDirty: boolean;
  onSave: () => Promise<boolean>;
  onDiscard: () => void;
}

interface RegisteredGuard extends UnsavedChangesGuardHandlers {
  id: number;
}

export interface UnsavedChangesContextValue {
  setGuard: (id: number, handlers: UnsavedChangesGuardHandlers) => void;
  removeGuard: (id: number) => void;
  requestClose: (id: number) => void;
  getGuards: () => ReadonlyArray<RegisteredGuard>;
}

export const UnsavedChangesContext = createContext<UnsavedChangesContextValue | null>(null);

export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const guardsRef = useRef<RegisteredGuard[]>([]);
  const [pendingDialogGuardId, setPendingDialogGuardId] = useState<number | null>(null);

  const findGuard = useCallback((id: number) => guardsRef.current.find(g => g.id === id) ?? null, []);

  const setGuard = useCallback((id: number, handlers: UnsavedChangesGuardHandlers) => {
    const existing = findGuard(id);
    if (existing) {
      existing.isDirty = handlers.isDirty;
      existing.onSave = handlers.onSave;
      existing.onDiscard = handlers.onDiscard;
      existing.kind = handlers.kind;
    } else {
      guardsRef.current = [...guardsRef.current, { id, ...handlers }];
    }
  }, [findGuard]);

  const removeGuard = useCallback((id: number) => {
    guardsRef.current = guardsRef.current.filter(g => g.id !== id);
    setPendingDialogGuardId(current => (current === id ? null : current));
  }, []);

  const requestClose = useCallback((id: number) => {
    const guard = findGuard(id);
    if (!guard) return;
    if (!guard.isDirty) {
      guard.onDiscard();
      return;
    }
    setPendingDialogGuardId(id);
  }, [findGuard]);

  const getGuards = useCallback(() => guardsRef.current, []);

  return (
    <UnsavedChangesContext.Provider value={{ setGuard, removeGuard, requestClose, getGuards }}>
      {children}
      {/* Task 2 replaces this marker with the real dialog, driven by pendingDialogGuardId. */}
      <UnsavedChangesTestOnlyState pendingDialogGuardId={pendingDialogGuardId} />
    </UnsavedChangesContext.Provider>
  );
}

// Exposes internal state for tests only (Task 2 removes this in favor of the
// real dialog component consuming the same state directly inside the provider).
const InternalsContext = createContext<{ pendingDialogGuardId: number | null }>({ pendingDialogGuardId: null });
function UnsavedChangesTestOnlyState({ pendingDialogGuardId }: { pendingDialogGuardId: number | null }) {
  return (
    <InternalsContext.Provider value={{ pendingDialogGuardId }}>
      <></>
    </InternalsContext.Provider>
  );
}
export function useUnsavedChangesInternalsForTests() {
  return useContext(InternalsContext);
}
```

- [ ] **Step 4: Write the hook**

```ts
// frontend/src/hooks/useUnsavedChangesGuard.ts
import { useContext, useEffect, useRef } from "react";
import { UnsavedChangesContext, UnsavedChangesGuardHandlers } from "../contexts/UnsavedChangesContext";

let nextGuardId = 0;

export function useUnsavedChangesGuard(handlers: UnsavedChangesGuardHandlers): { requestClose: () => void } {
  const ctx = useContext(UnsavedChangesContext);
  const idRef = useRef<number>();
  if (idRef.current === undefined) idRef.current = ++nextGuardId;
  const id = idRef.current;

  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    if (!ctx) return;
    ctx.setGuard(id, {
      kind: handlersRef.current.kind,
      isDirty: handlersRef.current.isDirty,
      onSave: () => handlersRef.current.onSave(),
      onDiscard: () => handlersRef.current.onDiscard(),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx, id, handlers.isDirty, handlers.kind]);

  useEffect(() => {
    return () => ctx?.removeGuard(id);
  }, [ctx, id]);

  return {
    requestClose: () => {
      if (!ctx || !handlersRef.current.isDirty) {
        handlersRef.current.onDiscard();
        return;
      }
      ctx.requestClose(id);
    },
  };
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run src/hooks/useUnsavedChangesGuard.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/contexts/UnsavedChangesContext.tsx frontend/src/hooks/useUnsavedChangesGuard.ts frontend/src/hooks/useUnsavedChangesGuard.test.tsx
git commit -m "feat: add unsaved-changes guard registry and hook"
```

---

### Task 2: `UnsavedChangesDialog` + wire it to `requestClose`

**Files:**
- Create: `frontend/src/components/UnsavedChangesDialog.tsx`
- Modify: `frontend/src/contexts/UnsavedChangesContext.tsx` (replace the Task-1 test-only marker with the real dialog)
- Test: `frontend/src/contexts/UnsavedChangesContext.test.tsx` (new — supersedes the internals-probe tests added in Task 1, which move here and are rewritten against the real dialog)

**Interfaces:**
- Consumes: `UnsavedChangesContext`, `useUnsavedChangesGuard` from Task 1.
- Produces: `UnsavedChangesDialog` props `{ open: boolean; saving: boolean; error: string | null; onSaveAndLeave: () => void; onDiscardAndLeave: () => void; onCancel: () => void }`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/contexts/UnsavedChangesContext.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useState } from "react";
import { UnsavedChangesProvider } from "./UnsavedChangesContext";
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard";

function DirtyForm({ onSave, onDiscard }: { onSave: () => Promise<boolean>; onDiscard: () => void }) {
  const [dirty, setDirty] = useState(true);
  const { requestClose } = useUnsavedChangesGuard({ kind: "modal", isDirty: dirty, onSave, onDiscard: () => { setDirty(false); onDiscard(); } });
  return <button onClick={requestClose} data-testid="close">close</button>;
}

describe("UnsavedChangesContext dialog", () => {
  it("shows nothing when no guard requested a close", () => {
    render(<UnsavedChangesProvider><div /></UnsavedChangesProvider>);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("discard and leave calls onDiscard and closes the dialog", () => {
    const onDiscard = vi.fn();
    render(<UnsavedChangesProvider><DirtyForm onSave={vi.fn()} onDiscard={onDiscard} /></UnsavedChangesProvider>);
    fireEvent.click(screen.getByTestId("close"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("unsaved-discard"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancel closes the dialog without calling onDiscard or onSave", () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn();
    render(<UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-cancel"));
    expect(onDiscard).not.toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("save and leave calls onSave, then onDiscard once it resolves true", async () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn().mockResolvedValue(true);
    render(<UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(onDiscard).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("save and leave shows a retry error and stays open when onSave resolves false", async () => {
    const onDiscard = vi.fn();
    const onSave = vi.fn().mockResolvedValue(false);
    render(<UnsavedChangesProvider><DirtyForm onSave={onSave} onDiscard={onDiscard} /></UnsavedChangesProvider>);
    fireEvent.click(screen.getByTestId("close"));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(screen.getByTestId("unsaved-error")).toBeInTheDocument());
    expect(onDiscard).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/contexts/UnsavedChangesContext.test.tsx`
Expected: FAIL — no dialog is rendered yet (`role="dialog"` never appears).

- [ ] **Step 3: Write the dialog component**

```tsx
// frontend/src/components/UnsavedChangesDialog.tsx
interface Props {
  open: boolean;
  saving: boolean;
  error: string | null;
  onSaveAndLeave: () => void;
  onDiscardAndLeave: () => void;
  onCancel: () => void;
}

export default function UnsavedChangesDialog({ open, saving, error, onSaveAndLeave, onDiscardAndLeave, onCancel }: Props) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-[100]" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        dir="rtl"
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-5 w-80"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="font-semibold text-base mb-2">יש שינויים שלא נשמרו</h3>
        <p className="text-sm text-gray-600 dark:text-gray-300 mb-3">
          אם תצא/י עכשיו, השינויים שביצעת יאבדו. מה לעשות?
        </p>
        {error && <p data-testid="unsaved-error" className="text-red-500 text-xs mb-3">{error}</p>}
        <div className="flex flex-col gap-2">
          <button
            type="button"
            data-testid="unsaved-save"
            disabled={saving}
            onClick={onSaveAndLeave}
            className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
          >
            {saving ? "שומר..." : "שמור וצא"}
          </button>
          <button
            type="button"
            data-testid="unsaved-discard"
            disabled={saving}
            onClick={onDiscardAndLeave}
            className="border border-red-300 text-red-700 px-3 py-1.5 rounded text-sm disabled:opacity-50"
          >
            צא בלי לשמור
          </button>
          <button
            type="button"
            data-testid="unsaved-cancel"
            disabled={saving}
            onClick={onCancel}
            className="text-sm text-gray-500 dark:text-gray-400 hover:underline disabled:opacity-50"
          >
            ביטול
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire the dialog into the provider**

Replace the `UnsavedChangesTestOnlyState`/`InternalsContext` block from Task 1 in `frontend/src/contexts/UnsavedChangesContext.tsx` with:

```tsx
import UnsavedChangesDialog from "../components/UnsavedChangesDialog";
// (keep the existing createContext/useCallback/useRef/useState imports, add useState-based dialog fields)

interface DialogState {
  guardId: number;
  saving: boolean;
  error: string | null;
}

// inside UnsavedChangesProvider, replace the pendingDialogGuardId state with:
const [dialog, setDialog] = useState<DialogState | null>(null);

const requestClose = useCallback((id: number) => {
  const guard = findGuard(id);
  if (!guard) return;
  if (!guard.isDirty) {
    guard.onDiscard();
    return;
  }
  setDialog({ guardId: id, saving: false, error: null });
}, [findGuard]);

// removeGuard also clears a dialog pointing at the removed guard:
const removeGuard = useCallback((id: number) => {
  guardsRef.current = guardsRef.current.filter(g => g.id !== id);
  setDialog(current => (current?.guardId === id ? null : current));
}, []);

const handleSaveAndLeave = useCallback(async () => {
  if (!dialog) return;
  const guard = findGuard(dialog.guardId);
  if (!guard) { setDialog(null); return; }
  setDialog(d => (d ? { ...d, saving: true, error: null } : d));
  const ok = await guard.onSave();
  if (ok) {
    guard.onDiscard();
    setDialog(null);
  } else {
    setDialog(d => (d ? { ...d, saving: false, error: "השמירה נכשלה. נסה שוב." } : d));
  }
}, [dialog, findGuard]);

const handleDiscardAndLeave = useCallback(() => {
  if (!dialog) return;
  const guard = findGuard(dialog.guardId);
  guard?.onDiscard();
  setDialog(null);
}, [dialog, findGuard]);

const handleCancel = useCallback(() => setDialog(null), []);

// JSX returned by the provider:
return (
  <UnsavedChangesContext.Provider value={{ setGuard, removeGuard, requestClose, getGuards }}>
    {children}
    <UnsavedChangesDialog
      open={dialog !== null}
      saving={dialog?.saving ?? false}
      error={dialog?.error ?? null}
      onSaveAndLeave={() => { void handleSaveAndLeave(); }}
      onDiscardAndLeave={handleDiscardAndLeave}
      onCancel={handleCancel}
    />
  </UnsavedChangesContext.Provider>
);
```

Delete the `InternalsContext`/`useUnsavedChangesInternalsForTests` export and its use. Replace Task 1's `frontend/src/hooks/useUnsavedChangesGuard.test.tsx` in full with this version, which drops `PendingProbe`/`useUnsavedChangesInternalsForTests` in favor of asserting on the real dialog:

```tsx
// frontend/src/hooks/useUnsavedChangesGuard.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useState } from "react";
import { UnsavedChangesProvider } from "../contexts/UnsavedChangesContext";
import { useUnsavedChangesGuard } from "./useUnsavedChangesGuard";

function DirtyPage({ onSave, onDiscard }: { onSave: () => Promise<boolean>; onDiscard: () => void }) {
  const [dirty, setDirty] = useState(false);
  const { requestClose } = useUnsavedChangesGuard({ kind: "page", isDirty: dirty, onSave, onDiscard });
  return (
    <div>
      <button onClick={() => setDirty(true)} data-testid="make-dirty">dirty</button>
      <button onClick={requestClose} data-testid="request-close">close</button>
    </div>
  );
}

describe("useUnsavedChangesGuard", () => {
  it("discards immediately when not dirty", () => {
    const onDiscard = vi.fn();
    render(
      <UnsavedChangesProvider>
        <DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />
      </UnsavedChangesProvider>,
    );
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the confirmation dialog instead of discarding when dirty", () => {
    const onDiscard = vi.fn();
    render(
      <UnsavedChangesProvider>
        <DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />
      </UnsavedChangesProvider>,
    );
    fireEvent.click(screen.getByTestId("make-dirty"));
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("discards immediately (no provider) when used outside a provider", () => {
    const onDiscard = vi.fn();
    render(<DirtyPage onSave={vi.fn()} onDiscard={onDiscard} />);
    fireEvent.click(screen.getByTestId("make-dirty"));
    fireEvent.click(screen.getByTestId("request-close"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
  });
});
```

Note this drops the original Task 1 test's `console.error` spy (that test was probing a code path — `!ctx` — that doesn't warn to the console; the spy was unnecessary and is removed here rather than carried forward).

- [ ] **Step 5: Run both test files to verify they pass**

Run: `npx vitest run src/contexts/UnsavedChangesContext.test.tsx src/hooks/useUnsavedChangesGuard.test.tsx`
Expected: PASS (8 tests total)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/UnsavedChangesDialog.tsx frontend/src/contexts/UnsavedChangesContext.tsx frontend/src/contexts/UnsavedChangesContext.test.tsx frontend/src/hooks/useUnsavedChangesGuard.test.tsx
git commit -m "feat: add the unsaved-changes confirmation dialog"
```

---

### Task 3: `beforeunload` interception

**Files:**
- Modify: `frontend/src/contexts/UnsavedChangesContext.tsx`
- Test: `frontend/src/contexts/UnsavedChangesContext.test.tsx` (add cases)

**Interfaces:**
- Consumes: `guardsRef` from the provider (Task 1/2).
- Produces: no new exports — internal behavior only.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/contexts/UnsavedChangesContext.test.tsx`:

```tsx
describe("UnsavedChangesContext beforeunload", () => {
  it("prevents unload while a guard is dirty", () => {
    render(<UnsavedChangesProvider><DirtyForm onSave={vi.fn()} onDiscard={vi.fn()} /></UnsavedChangesProvider>);
    const event = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
    const preventDefault = vi.spyOn(event, "preventDefault");
    window.dispatchEvent(event);
    expect(preventDefault).toHaveBeenCalled();
  });

  it("does not prevent unload once nothing is dirty", () => {
    function CleanForm() {
      useUnsavedChangesGuard({ kind: "modal", isDirty: false, onSave: vi.fn(), onDiscard: vi.fn() });
      return null;
    }
    render(<UnsavedChangesProvider><CleanForm /></UnsavedChangesProvider>);
    const event = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
    const preventDefault = vi.spyOn(event, "preventDefault");
    window.dispatchEvent(event);
    expect(preventDefault).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/contexts/UnsavedChangesContext.test.tsx`
Expected: FAIL — the two new tests fail (`preventDefault` never called).

- [ ] **Step 3: Add the listener**

Add inside `UnsavedChangesProvider`, alongside the other hooks:

```tsx
useEffect(() => {
  function handleBeforeUnload(e: BeforeUnloadEvent) {
    if (!guardsRef.current.some(g => g.isDirty)) return;
    e.preventDefault();
    e.returnValue = "";
  }
  window.addEventListener("beforeunload", handleBeforeUnload);
  return () => window.removeEventListener("beforeunload", handleBeforeUnload);
}, []);
```

(Add `useEffect` to the existing `react` import line at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/contexts/UnsavedChangesContext.test.tsx`
Expected: PASS (10 tests total)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/contexts/UnsavedChangesContext.tsx frontend/src/contexts/UnsavedChangesContext.test.tsx
git commit -m "feat: warn on tab close/refresh while a guard is dirty"
```

---

### Task 4: In-app link-click interception

**Files:**
- Modify: `frontend/src/contexts/UnsavedChangesContext.tsx`
- Test: `frontend/src/contexts/UnsavedChangesContext.test.tsx` (add cases)

**Interfaces:**
- Consumes: `useNavigate` from `react-router-dom` — this means `UnsavedChangesProvider` must be mounted inside a `<BrowserRouter>` (documented in Task 6).
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/contexts/UnsavedChangesContext.test.tsx` (add `MemoryRouter`/`Routes`/`Route`/`Link` to the `react-router-dom` import at the top of the file):

```tsx
import { MemoryRouter, Routes, Route, Link } from "react-router-dom";

function PageWithLink({ isDirty }: { isDirty: boolean }) {
  useUnsavedChangesGuard({ kind: "page", isDirty, onSave: vi.fn().mockResolvedValue(true), onDiscard: vi.fn() });
  return <Link to="/other">go</Link>;
}

describe("UnsavedChangesContext in-app link interception", () => {
  it("lets navigation proceed immediately when nothing is dirty", () => {
    render(
      <MemoryRouter initialEntries={["/here"]}>
        <UnsavedChangesProvider>
          <Routes>
            <Route path="/here" element={<PageWithLink isDirty={false} />} />
            <Route path="/other" element={<div data-testid="other-page">other</div>} />
          </Routes>
        </UnsavedChangesProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText("go"));
    expect(screen.getByTestId("other-page")).toBeInTheDocument();
  });

  it("intercepts the click and shows the dialog when dirty, navigating only after confirming discard", () => {
    render(
      <MemoryRouter initialEntries={["/here"]}>
        <UnsavedChangesProvider>
          <Routes>
            <Route path="/here" element={<PageWithLink isDirty={true} />} />
            <Route path="/other" element={<div data-testid="other-page">other</div>} />
          </Routes>
        </UnsavedChangesProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText("go"));
    expect(screen.queryByTestId("other-page")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("unsaved-discard"));
    expect(screen.getByTestId("other-page")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/contexts/UnsavedChangesContext.test.tsx`
Expected: FAIL — the dirty case navigates immediately (no interception yet).

- [ ] **Step 3: Add the click interceptor**

Add `import { useNavigate } from "react-router-dom";` to `UnsavedChangesContext.tsx` (no such import exists yet — this is the first task that needs the router), and inside the provider:

```tsx
const navigate = useNavigate();

useEffect(() => {
  function activeDirtyGuard() {
    const guards = guardsRef.current;
    for (let i = guards.length - 1; i >= 0; i--) {
      if (guards[i].isDirty) return guards[i];
    }
    return null;
  }

  function handleClick(e: MouseEvent) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const guard = activeDirtyGuard();
    if (!guard) return;
    const target = e.target as HTMLElement | null;
    const anchor = target?.closest("a[href]") as HTMLAnchorElement | null;
    if (!anchor) return;
    if (anchor.target && anchor.target !== "_self") return;
    const url = new URL(anchor.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    e.preventDefault();
    const destination = url.pathname + url.search + url.hash;
    setDialog({ guardId: guard.id, saving: false, error: null, onLeave: () => navigate(destination) });
  }

  document.addEventListener("click", handleClick, true);
  return () => document.removeEventListener("click", handleClick, true);
}, [navigate]);
```

This introduces an `onLeave` field the dialog state didn't have before — extend `DialogState` and both handlers to use it, defaulting to a no-op for the plain `requestClose` path (which doesn't need extra navigation beyond the guard's own `onDiscard`):

```tsx
interface DialogState {
  guardId: number;
  saving: boolean;
  error: string | null;
  onLeave?: () => void; // extra action after a confirmed discard/save (e.g. navigate); optional for the requestClose path
}
```

Update `handleSaveAndLeave` and `handleDiscardAndLeave` (from Task 2) to call `dialog.onLeave?.()` after `guard.onDiscard()`:

```tsx
const handleSaveAndLeave = useCallback(async () => {
  if (!dialog) return;
  const guard = findGuard(dialog.guardId);
  if (!guard) { setDialog(null); return; }
  setDialog(d => (d ? { ...d, saving: true, error: null } : d));
  const ok = await guard.onSave();
  if (ok) {
    guard.onDiscard();
    dialog.onLeave?.();
    setDialog(null);
  } else {
    setDialog(d => (d ? { ...d, saving: false, error: "השמירה נכשלה. נסה שוב." } : d));
  }
}, [dialog, findGuard]);

const handleDiscardAndLeave = useCallback(() => {
  if (!dialog) return;
  const guard = findGuard(dialog.guardId);
  guard?.onDiscard();
  dialog?.onLeave?.();
  setDialog(null);
}, [dialog, findGuard]);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/contexts/UnsavedChangesContext.test.tsx`
Expected: PASS (12 tests total)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/contexts/UnsavedChangesContext.tsx frontend/src/contexts/UnsavedChangesContext.test.tsx
git commit -m "feat: confirm before an in-app navigation click discards unsaved changes"
```

---

### Task 5: Back/forward (`popstate`) interception for page guards

**Files:**
- Modify: `frontend/src/contexts/UnsavedChangesContext.tsx`
- Test: `frontend/src/contexts/UnsavedChangesContext.test.tsx` (add cases)

**Interfaces:**
- Consumes: `RegisteredGuard.kind` (only `"page"` guards participate here — `"modal"` guards are handled by `useModalBackClose` + `requestClose`, unaffected by this task).
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/contexts/UnsavedChangesContext.test.tsx`:

```tsx
describe("UnsavedChangesContext back/forward interception", () => {
  it("cancels a real back-press while a page guard is dirty and shows the dialog", async () => {
    function DirtyPage() {
      useUnsavedChangesGuard({ kind: "page", isDirty: true, onSave: vi.fn(), onDiscard: vi.fn() });
      return <div data-testid="dirty-page">here</div>;
    }
    render(
      <MemoryRouter initialEntries={["/start", "/here"]} initialIndex={1}>
        <UnsavedChangesProvider>
          <DirtyPage />
        </UnsavedChangesProvider>
      </MemoryRouter>,
    );
    // Let the "push a sentinel while dirty" effect run.
    await waitFor(() => expect(window.history.length).toBeGreaterThan(0));
    act(() => { window.history.back(); });
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(screen.getByTestId("dirty-page")).toBeInTheDocument();
  });

  it("a modal-kind guard does not trigger the page back interception", () => {
    function DirtyModalGuard() {
      useUnsavedChangesGuard({ kind: "modal", isDirty: true, onSave: vi.fn(), onDiscard: vi.fn() });
      return null;
    }
    render(
      <MemoryRouter initialEntries={["/start", "/here"]} initialIndex={1}>
        <UnsavedChangesProvider><DirtyModalGuard /></UnsavedChangesProvider>
      </MemoryRouter>,
    );
    act(() => { window.history.back(); });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/contexts/UnsavedChangesContext.test.tsx`
Expected: FAIL — no back-press interception exists yet, so no dialog appears in the first test.

- [ ] **Step 3: Add the sentinel-based interceptor**

Add inside `UnsavedChangesProvider`:

```tsx
const sentinelActiveRef = useRef(false);

function anyDirtyPageGuard() {
  return guardsRef.current.some(g => g.kind === "page" && g.isDirty);
}
function activeDirtyPageGuard() {
  const guards = guardsRef.current;
  for (let i = guards.length - 1; i >= 0; i--) {
    if (guards[i].kind === "page" && guards[i].isDirty) return guards[i];
  }
  return null;
}

// Ensures one extra history entry sits on top whenever a page guard is dirty,
// so the next back-press pops that sentinel (caught below) instead of
// leaving the page. Deliberately does not pop the sentinel back off when a
// guard becomes clean again -- popping here would itself fire a popstate and
// risk interfering with in-flight app navigation. An inert leftover sentinel
// is harmless: the next real back-press pops it, handlePopState below sees
// nothing is dirty, and lets that pop stand.
useEffect(() => {
  if (anyDirtyPageGuard() && !sentinelActiveRef.current) {
    window.history.pushState({ __unsavedGuardSentinel: true }, "");
    sentinelActiveRef.current = true;
  }
});

useEffect(() => {
  function handlePopState() {
    if (!sentinelActiveRef.current) return;
    sentinelActiveRef.current = false;
    const guard = activeDirtyPageGuard();
    if (!guard) return; // nothing dirty -- let the back-press stand
    // Cancel the navigation: push the sentinel back on top and ask first.
    window.history.pushState({ __unsavedGuardSentinel: true }, "");
    sentinelActiveRef.current = true;
    setDialog({
      guardId: guard.id,
      saving: false,
      error: null,
      onLeave: () => {
        sentinelActiveRef.current = false;
        window.history.go(-2);
      },
    });
  }
  window.addEventListener("popstate", handlePopState);
  return () => window.removeEventListener("popstate", handlePopState);
}, []);
```

The first effect (no dependency array) runs after every render, which is what lets it notice a guard's `isDirty` flipping true even though that change lives in a ref, not React state — cheap because the body is a single ref check when nothing changed.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/contexts/UnsavedChangesContext.test.tsx`
Expected: PASS (14 tests total)

- [ ] **Step 5: Run the full frontend test suite to check for regressions**

Run: `cd frontend && npx vitest run`
Expected: PASS, no regressions (particularly `useModalBackClose.test.tsx`, which this task's history manipulation must not interfere with since it targets a disjoint code path today — no modal guards are wired up until Task 8/9).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/contexts/UnsavedChangesContext.tsx frontend/src/contexts/UnsavedChangesContext.test.tsx
git commit -m "feat: confirm before the browser back/forward buttons discard a dirty page"
```

---

### Task 6: Mount the provider

**Files:**
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: `UnsavedChangesProvider` from Task 1-5.

- [ ] **Step 1: Add the provider inside `<BrowserRouter>`**

```tsx
import { UnsavedChangesProvider } from "./contexts/UnsavedChangesContext";
```

```tsx
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <UnsavedChangesProvider>
          <NavigationHistoryProvider>
            <AlgorithmSeenProvider>
              <App />
            </AlgorithmSeenProvider>
          </NavigationHistoryProvider>
        </UnsavedChangesProvider>
      </BrowserRouter>
    </QueryClientProvider>
```

(It must be inside `<BrowserRouter>` because it calls `useNavigate`, added in Task 4.)

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`
Expected: PASS — mounting an extra provider with no active guards should be inert everywhere else.

- [ ] **Step 3: Manually smoke-test in the dev server**

Start the stack (`.\dev.ps1` from the repo root) and open `http://localhost:5173`. Confirm the app still loads and navigates normally (nothing should visibly change yet — no component calls the hook until Task 7).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/main.tsx
git commit -m "feat: mount the unsaved-changes provider"
```

---

### Task 7: Integrate `SystemSettingsContent` (covers both `SystemSettingsPage` and `AdminSettingsPage`)

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Test: `frontend/src/pages/SystemSettingsPage.test.tsx`

**Interfaces:**
- Consumes: `useUnsavedChangesGuard` from Task 1.

`AdminSettingsPage.tsx` renders `<SystemSettingsContent />` directly (tab 0) with no wrapper of its own, so this one change covers both pages.

- [ ] **Step 1: Note the existing test file's rendering setup**

`SystemSettingsPage.test.tsx` renders `SystemSettingsContent` via its own `renderWithProviders(ui)` helper (query client only — no router, no `UnsavedChangesProvider`). Since `SystemSettingsContent` will now call `useUnsavedChangesGuard`, and the hook works fine with `ctx === null` (falls back to calling `onDiscard` immediately, per Task 1), every existing test in that file keeps passing unchanged — they just exercise the "no provider" fallback path, invisibly. The new test below wraps the same helper's render call in `MemoryRouter` + `UnsavedChangesProvider` explicitly, reusing the file's existing `beforeEach` mocks (`getSystemSettings` resolving `{ "eligibility.mitvahim_months": 6 }`, `getRankLadder` resolving the same three-track fixture already defined at the top of the file).

- [ ] **Step 2: Write the failing test**

Append to `frontend/src/pages/SystemSettingsPage.test.tsx`, adding these two new imports at the top of the file (neither exists there yet):

```tsx
import { MemoryRouter } from "react-router-dom";
import { UnsavedChangesProvider } from "../contexts/UnsavedChangesContext";

function renderWithUnsavedChangesGuard(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <UnsavedChangesProvider>{ui}</UnsavedChangesProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("SystemSettingsContent unsaved-changes guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(systemSettingsApi.getSystemSettings).mockResolvedValue({
      "eligibility.mitvahim_months": 6,
    });
    vi.mocked(rankAdvancementApi.getRankLadder).mockResolvedValue({
      enlisted: [{ rank: "טוראי", months_to_next: 4, advance_on_career_entry: false }],
      officer: [{ rank: "סגן", months_to_next: 12, advance_on_career_entry: false }],
      officer_academic: [{ rank: "קאב", months_to_next: null, advance_on_career_entry: false }],
    });
  });

  it("warns before a browser tab close while a boolean setting is toggled", async () => {
    renderWithUnsavedChangesGuard(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());
    const [firstUntoggled] = screen.getAllByRole("button", { pressed: false });
    fireEvent.click(firstUntoggled);

    const event = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
    const preventDefault = vi.spyOn(event, "preventDefault");
    window.dispatchEvent(event);
    expect(preventDefault).toHaveBeenCalled();
  });

  it("does not warn before a tab close when nothing was changed", async () => {
    renderWithUnsavedChangesGuard(<SystemSettingsContent />);
    await waitFor(() => expect(systemSettingsApi.getSystemSettings).toHaveBeenCalled());

    const event = new Event("beforeunload", { cancelable: true }) as BeforeUnloadEvent;
    const preventDefault = vi.spyOn(event, "preventDefault");
    window.dispatchEvent(event);
    expect(preventDefault).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/SystemSettingsPage.test.tsx`
Expected: FAIL — `SystemSettingsContent` doesn't call the hook yet, so `preventDefault` is never called.

- [ ] **Step 4: Wire the hook into `SystemSettingsContent`**

In `frontend/src/pages/SystemSettingsPage.tsx`, add the import:

```ts
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard";
```

Inside `SystemSettingsContent`, right after the existing `const isDirty = JSON.stringify(draft) !== JSON.stringify(settings);` (`SystemSettingsPage.tsx:516`), add:

```ts
useUnsavedChangesGuard({
  kind: "page",
  isDirty,
  onSave: async () => {
    try {
      await saveMutation.mutateAsync(draft);
      return true;
    } catch {
      return false;
    }
  },
  onDiscard: () => setDraft(settings),
});
```

No changes needed to the JSX — `SystemSettingsContent` has no internal close trigger; the provider's global `beforeunload`/click/back-button interception (Tasks 3-5) does the rest automatically once this hook call registers the guard.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/SystemSettingsPage.test.tsx`
Expected: PASS

- [ ] **Step 6: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`
Expected: PASS, no regressions to existing `SystemSettingsPage.test.tsx` or `AdminSettingsPage.test.tsx` cases.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx frontend/src/pages/SystemSettingsPage.test.tsx
git commit -m "feat: warn before leaving system settings with unsaved edits"
```

---

### Task 8: Integrate `LocationFormModal` (simple local-mutation exemplar)

**Files:**
- Modify: `frontend/src/components/LocationFormModal.tsx`
- Test: `frontend/src/components/LocationFormModal.test.tsx` (create if it doesn't exist yet — check first)

**Interfaces:**
- Consumes: `useUnsavedChangesGuard` from Task 1.

- [ ] **Step 1: Check for an existing test file**

Run: `ls frontend/src/components/LocationFormModal.test.tsx 2>/dev/null || echo "none"`

If it exists, add the new `describe` block from Step 2 to it, matching its existing mocking style for `createLocation`. If not, create it fresh using the pattern below (mock `../api/dutyConfig`'s `createLocation`).

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/components/LocationFormModal.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import LocationFormModal from "./LocationFormModal";
import { UnsavedChangesProvider } from "../contexts/UnsavedChangesContext";

vi.mock("../api/dutyConfig", () => ({
  createLocation: vi.fn(),
}));

function renderModal(onCreated = vi.fn(), onClose = vi.fn()) {
  return {
    onCreated, onClose,
    ...render(
      <MemoryRouter>
        <UnsavedChangesProvider>
          <LocationFormModal onCreated={onCreated} onClose={onClose} />
        </UnsavedChangesProvider>
      </MemoryRouter>,
    ),
  };
}

describe("LocationFormModal unsaved-changes guard", () => {
  it("closes immediately when the name field is untouched", () => {
    const { onClose } = renderModal();
    fireEvent.click(screen.getByText("✕"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("confirms before discarding a typed name via the backdrop", () => {
    const { onClose } = renderModal();
    fireEvent.change(screen.getByTestId("location-create-name"), { target: { value: "מטווח חדש" } });
    fireEvent.click(screen.getByText("✕"));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("unsaved-discard"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("save and leave creates the location then closes", async () => {
    const dutyConfig = await import("../api/dutyConfig");
    const created = { id: "loc1", name: "מטווח חדש" };
    vi.mocked(dutyConfig.createLocation).mockResolvedValue(created);
    const { onCreated, onClose } = renderModal();
    fireEvent.change(screen.getByTestId("location-create-name"), { target: { value: "מטווח חדש" } });
    fireEvent.click(screen.getByText("✕"));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onCreated).toHaveBeenCalledWith(created);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/LocationFormModal.test.tsx`
Expected: FAIL — clicking ✕ with a typed name closes immediately today (no dialog).

- [ ] **Step 4: Refactor the save logic into a reusable function and wire the guard**

```tsx
// frontend/src/components/LocationFormModal.tsx
import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyLocation, createLocation } from "../api/dutyConfig";
import { translateApiError } from "../utils/translateApiError";
import { useModalBackClose } from "../hooks/useModalBackClose";
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard";

interface Props {
  onCreated: (loc: DutyLocation) => void;
  onClose: () => void;
}

export default function LocationFormModal({ onCreated, onClose }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function trySave(): Promise<boolean> {
    setError(null);
    setSaving(true);
    try {
      const loc = await createLocation({ name: name.trim() });
      onCreated(loc);
      return true;
    } catch (err: unknown) {
      setError(translateApiError(err, t, "שגיאה"));
      return false;
    } finally {
      setSaving(false);
    }
  }

  const { requestClose } = useUnsavedChangesGuard({
    kind: "modal",
    isDirty: name.trim() !== "",
    onSave: trySave,
    onDiscard: onClose,
  });
  useModalBackClose(requestClose);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    await trySave();
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={requestClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-80" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-base">{t("duty_config.add")} {t("duty_config.locations")}</h3>
          <button type="button" onClick={requestClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <label className="block text-sm">
            {t("duty_config.name")}
            <input
              required
              autoFocus
              value={name}
              onChange={e => setName(e.target.value)}
              data-testid="location-create-name"
              className="mt-1 block w-full border rounded p-1.5 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            />
          </label>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={requestClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">
              {t("duty_config.cancel", "ביטול")}
            </button>
            <button type="submit" disabled={saving || !name.trim()}
              data-testid="location-create-submit"
              className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">
              {t("duty_config.add")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/LocationFormModal.test.tsx`
Expected: PASS

- [ ] **Step 6: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`
Expected: PASS — check specifically any other test file that renders `LocationFormModal` outside an `UnsavedChangesProvider` (the hook's `ctx === null` fallback in Task 1 makes `requestClose` behave exactly like the old `onClose` in that case, so those should be unaffected).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/LocationFormModal.tsx frontend/src/components/LocationFormModal.test.tsx
git commit -m "feat: confirm before discarding an unsaved new location"
```

---

### Task 9: Integrate `SoldierEditModal` (parent-owned save + diff-based dirty exemplar)

**Files:**
- Modify: `frontend/src/components/SoldierEditModal.tsx`
- Test: `frontend/src/components/SoldierEditModal.test.tsx` (create if it doesn't exist yet — check first, same as Task 8 Step 1)

**Interfaces:**
- Consumes: `useUnsavedChangesGuard` from Task 1.

- [ ] **Step 1: Check for an existing test file, and write the failing test**

```tsx
// frontend/src/components/SoldierEditModal.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import SoldierEditModal from "./SoldierEditModal";
import { UnsavedChangesProvider } from "../contexts/UnsavedChangesContext";
import * as hierarchyApi from "../api/hierarchy";

vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn().mockResolvedValue([]),
}));

const soldier = { id: "s1", full_name: "אורי כהן", phone: "0500000000", hierarchy_node_id: "n1" } as never;

function renderModal(onSave = vi.fn().mockResolvedValue(undefined), onClose = vi.fn()) {
  return {
    onSave, onClose,
    ...render(
      <MemoryRouter>
        <UnsavedChangesProvider>
          <SoldierEditModal soldier={soldier} onSave={onSave} onClose={onClose} />
        </UnsavedChangesProvider>
      </MemoryRouter>,
    ),
  };
}

describe("SoldierEditModal unsaved-changes guard", () => {
  it("closes immediately when nothing changed", async () => {
    const { onClose } = renderModal();
    await waitFor(() => expect(hierarchyApi.fetchTree).toHaveBeenCalled());
    fireEvent.click(screen.getByText("ביטול", { selector: "button" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("confirms before discarding an edited name via cancel", async () => {
    const { onClose } = renderModal();
    await waitFor(() => expect(hierarchyApi.fetchTree).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("edit-soldier-name"), { target: { value: "אורי לוי" } });
    fireEvent.click(screen.getByText("ביטול", { selector: "button" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("unsaved-discard"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("save and leave calls the parent onSave with the diff, then closes", async () => {
    const { onSave, onClose } = renderModal();
    await waitFor(() => expect(hierarchyApi.fetchTree).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("edit-soldier-name"), { target: { value: "אורי לוי" } });
    fireEvent.click(screen.getByText("ביטול", { selector: "button" }));
    fireEvent.click(screen.getByTestId("unsaved-save"));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith({ full_name: "אורי לוי" });
  });
});
```

Note for the implementer: run `ls frontend/src/components/SoldierEditModal.test.tsx` first; if it already exists, append this `describe` block to it instead of creating a new file, matching whatever `soldier` fixture and `fetchTree` mock it already defines rather than redefining them.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/SoldierEditModal.test.tsx`
Expected: FAIL — cancel discards the edited name immediately today.

- [ ] **Step 3: Wire the guard in, reusing the existing diff computation as both `isDirty` and the save payload**

```tsx
// frontend/src/components/SoldierEditModal.tsx
import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import { SoldierDTO } from "../api/soldiers";
import { sortNodesByTree } from "../utils/sortNodesByTree";
import Combobox from "./Combobox";
import { useModalBackClose } from "../hooks/useModalBackClose";
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard";

interface Props {
  soldier: SoldierDTO;
  onSave: (data: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null }) => Promise<void>;
  onClose: () => void;
}

export default function SoldierEditModal({ soldier, onSave, onClose }: Props) {
  const { t } = useTranslation();
  const [fullName, setFullName] = useState(soldier.full_name);
  const [phone, setPhone] = useState(soldier.phone ?? "");
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [hierarchyNodeId, setHierarchyNodeId] = useState(soldier.hierarchy_node_id ?? "");

  useEffect(() => {
    void (async () => {
      const all = await fetchTree();
      setNodes(all);
    })();
  }, []);

  function diff() {
    const data: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null } = {};
    if (fullName !== soldier.full_name) data.full_name = fullName;
    if (phone !== (soldier.phone ?? "")) data.phone = phone || null;
    if (hierarchyNodeId !== (soldier.hierarchy_node_id ?? "")) data.hierarchy_node_id = hierarchyNodeId || null;
    return data;
  }

  async function trySave(): Promise<boolean> {
    try {
      await onSave(diff());
      return true;
    } catch {
      return false;
    }
  }

  const { requestClose } = useUnsavedChangesGuard({
    kind: "modal",
    isDirty: Object.keys(diff()).length > 0,
    onSave: trySave,
    onDiscard: onClose,
  });
  useModalBackClose(requestClose);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const ok = await trySave();
    if (ok) onClose();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={requestClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="soldier-edit-modal">
        <h3 className="font-semibold mb-4">{t("team.edit_soldier")}: {soldier.full_name}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <label className="block">
            <span className="text-xs">{t("team.full_name")}</span>
            <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={fullName} onChange={(e) => setFullName(e.target.value)} required data-testid="edit-soldier-name" />
          </label>
          <label className="block">
            <span className="text-xs">{t("profile.phone")}</span>
            <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={phone} onChange={(e) => setPhone(e.target.value)} data-testid="edit-soldier-phone" />
          </label>
          <label className="block">
            <span className="text-xs">{t("team.title")}</span>
            <Combobox
              items={sortNodesByTree(nodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
              value={hierarchyNodeId}
              onChange={setHierarchyNodeId}
              placeholder="—"
              testId="edit-soldier-node"
            />
          </label>
          <div className="flex justify-end gap-2">
            <button type="button" className="border dark:border-gray-600 dark:text-gray-300 rounded px-3 py-1" onClick={requestClose}>{t("team.cancel")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="edit-soldier-submit">{t("duty_config.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/SoldierEditModal.test.tsx`
Expected: PASS

- [ ] **Step 5: Run the full frontend test suite, then typecheck and lint**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`
Expected: all PASS — this is the last task in this plan, so it's the point to catch any lingering type or lint issue across every file touched (Tasks 1-9).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/SoldierEditModal.tsx frontend/src/components/SoldierEditModal.test.tsx
git commit -m "feat: confirm before discarding unsaved soldier-edit changes"
```

---

## Follow-up: rolling out to the remaining modals

This plan proves the pattern end-to-end (registry, dialog, all three page-level leave paths, and two structurally different modal shapes — a local-mutation create form and a parent-owned-save edit form) and ships it live on the two exemplars plus both settings pages. Every other modal with an actual editable field and a save action gets the same 4-line change demonstrated in Tasks 8-9:

1. Compute (or reuse) an `isDirty` boolean.
2. Call `useUnsavedChangesGuard({ kind: "modal", isDirty, onSave, onDiscard: onClose })`.
3. Route every internal close trigger (✕, backdrop `onClick`, Cancel button, and the callback passed to `useModalBackClose`) through the returned `requestClose` instead of `onClose`.
4. If the modal doesn't already have a single function that both explicit-Save and the guard's `onSave` can share, extract one (as Task 8 did with `trySave`).

Candidate files (from `grep -rl "fixed inset-0" frontend/src/components`), needing manual triage since some are read-only viewers with nothing to save and should be skipped:

```
AddChildNodeDialog.tsx          AddRootNodeDialog.tsx           AlgorithmModeHelpModal.tsx*
AskSwapModal.tsx                AssignCommanderDialog.tsx       AssignDutyManagersDialog.tsx
AutoAssignResponsibilityModal.tsx  BugReportDetailModal.tsx*    BugReportModal.tsx
BurdenShareBreakdownModal.tsx*  CoverOfferModal.tsx             DismissalModal.tsx
DocumentPreviewModal.tsx*       DutyManagerPortfolioDialog.tsx* DutyTypeFormModal.tsx
EditNodeDialog.tsx              EnrollmentApprovalModal.tsx     ExemptionInstanceModal.tsx
ExemptionTypeFormModal.tsx      ExemptionTypeViewModal.tsx*     ExplanationModal.tsx*
FairnessSpreadBreakdownModal.tsx*  GenerateShiftsModal.tsx      HelpModal.tsx*
HierarchyNodePickerModal.tsx*   ImportRowDetailModal.tsx*       ImportRowFieldsModal.tsx
OfferSwapModal.tsx              OverrideReasonModal.tsx         ReasonPromptModal.tsx
ReserveDismissalModal.tsx       SetResponsibleUnitsModal.tsx    ShiftAssignModal.tsx
ShiftFormModal.tsx              ShiftTemplateFormModal.tsx      SplitInUnitModal.tsx
UnifiedSoldierModal.tsx         dashboard/DutyDetailModal.tsx*  ranges/RangeEditAssignmentsModal.tsx
ranges/RangeBulkAutoAssignModal.tsx  planning/EventDetailModal.tsx (generic wrapper -- check each caller instead)
```

(`*` = likely a read-only viewer/picker with no save action — confirm and skip during triage rather than assuming.)

`RangeEditAssignmentsModal.tsx` and other multi-step/batch-edit modals (accumulate several pending changes before one explicit commit, rather than one flat form) need their own `isDirty` (e.g. "is the pending-changes list non-empty") but otherwise follow the identical recipe.

Given the size, doing this as its own follow-up plan (or a handful of subagent-driven tasks batching 5-8 files each) is more tractable than one further giant plan — each batch is still independently testable and shippable.
