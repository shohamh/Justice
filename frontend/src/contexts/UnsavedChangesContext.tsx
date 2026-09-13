import { createContext, ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";

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
    // The hook has already verified isDirty is true when it called this function.
    // Simply set the pending ID - the dialog UI (added in Task 2) will handle this.
    setPendingDialogGuardId(id);
  }, []);

  const getGuards = useCallback(() => guardsRef.current, []);

  const contextValue = useMemo(() => ({ setGuard, removeGuard, requestClose, getGuards }), [setGuard, removeGuard, requestClose, getGuards]);
  const internalsValue = useMemo(() => ({ pendingDialogGuardId }), [pendingDialogGuardId]);

  return (
    <UnsavedChangesContext.Provider value={contextValue}>
      <InternalsContext.Provider value={internalsValue}>
        {children}
        {/* Task 2 replaces this marker with the real dialog, driven by pendingDialogGuardId. */}
      </InternalsContext.Provider>
    </UnsavedChangesContext.Provider>
  );
}

// Exposes internal state for tests only (Task 2 removes this in favor of the
// real dialog component consuming the same state directly inside the provider).
const InternalsContext = createContext<{ pendingDialogGuardId: number | null }>({ pendingDialogGuardId: null });
export function useUnsavedChangesInternalsForTests() {
  return useContext(InternalsContext);
}
