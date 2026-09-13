import { createContext, ReactNode, useCallback, useMemo, useRef, useState } from "react";
import UnsavedChangesDialog from "../components/UnsavedChangesDialog";

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

interface DialogState {
  guardId: number;
  saving: boolean;
  error: string | null;
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
  const [dialog, setDialog] = useState<DialogState | null>(null);

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
    setDialog(current => (current?.guardId === id ? null : current));
  }, []);

  const requestClose = useCallback((id: number) => {
    const guard = findGuard(id);
    if (!guard) return;
    if (!guard.isDirty) {
      guard.onDiscard();
      return;
    }
    setDialog({ guardId: id, saving: false, error: null });
  }, [findGuard]);

  const getGuards = useCallback(() => guardsRef.current, []);

  const contextValue = useMemo(() => ({ setGuard, removeGuard, requestClose, getGuards }), [setGuard, removeGuard, requestClose, getGuards]);

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

  return (
    <UnsavedChangesContext.Provider value={contextValue}>
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
}
