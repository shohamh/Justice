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

type SentinelHistoryState = { __unsavedGuardSentinel?: boolean; __sentinelId?: number };

let nextSentinelId = 0;

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

  const sentinelActiveRef = useRef(false);
  // Identifies THIS provider's currently active sentinel push, not just its
  // shape -- a plain boolean-shaped marker would also match a stale sentinel
  // left behind by an earlier mount/unmount cycle sitting deeper in real
  // window.history (e.g. across tests sharing one jsdom window, or in principle
  // across remounts of this provider in the same tab), which must NOT be
  // mistaken for "we're still on our own current sentinel".
  const sentinelIdRef = useRef<number | null>(null);

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
      const id = ++nextSentinelId;
      sentinelIdRef.current = id;
      window.history.pushState({ __unsavedGuardSentinel: true, __sentinelId: id }, "");
      sentinelActiveRef.current = true;
    }
  });

  useEffect(() => {
    function handlePopState(e: PopStateEvent) {
      if (!sentinelActiveRef.current) return;
      // Some other mechanism (e.g. useModalBackClose's cleanup consuming its
      // own entry via history.back() when a modal closes by X/backdrop/Escape/
      // submit) can pop back onto OUR sentinel without the user having pressed
      // the browser back button at all. Checking that the landed-on state is
      // OUR own currently-active sentinel (by id, not just by shape) is how we
      // tell "we're still exactly where we should be" apart from "the user
      // genuinely navigated past the sentinel" -- only the latter should
      // cancel-and-ask. Matching by id rather than the bare marker matters:
      // a stale sentinel-shaped entry left deeper in history by an earlier
      // mount/unmount cycle of this provider must not be mistaken for the
      // current one.
      const landedState = (e.state ?? window.history.state) as SentinelHistoryState | null;
      if (landedState?.__unsavedGuardSentinel && landedState.__sentinelId === sentinelIdRef.current) return;
      sentinelActiveRef.current = false;
      const guard = activeDirtyPageGuard();
      if (!guard) return; // nothing dirty -- let the back-press stand
      // Cancel the navigation: push the sentinel back on top and ask first.
      const id = ++nextSentinelId;
      sentinelIdRef.current = id;
      window.history.pushState({ __unsavedGuardSentinel: true, __sentinelId: id }, "");
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
