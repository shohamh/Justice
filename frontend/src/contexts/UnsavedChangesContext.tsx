import { createContext, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
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
  onLeave?: () => void; // extra action after a confirmed discard/save (e.g. navigate); optional for the requestClose path
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
  const navigate = useNavigate();

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

  useEffect(() => {
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      if (!guardsRef.current.some(g => g.isDirty)) return;
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, []);

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
    let ok: boolean;
    try {
      ok = await guard.onSave();
    } catch {
      ok = false;
    }
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
