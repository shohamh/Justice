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
}

export const UnsavedChangesContext = createContext<UnsavedChangesContextValue | null>(null);

type SentinelHistoryState = { __unsavedGuardSentinel?: boolean; __sentinelId?: number };

let nextSentinelId = 0;

export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const guardsRef = useRef<RegisteredGuard[]>([]);
  const [dialog, setDialog] = useState<DialogState | null>(null);
  // Mirrors `dialog` synchronously in a ref so an async continuation (e.g. a
  // save promise resolving after the user has already dismissed the dialog
  // some other way) can check whether it's still the "live" dialog before
  // acting -- see handleSaveAndLeave.
  const dialogRef = useRef<DialogState | null>(null);
  dialogRef.current = dialog;
  const navigate = useNavigate();

  const findGuard = useCallback((id: number) => guardsRef.current.find(g => g.id === id) ?? null, []);

  // True whenever at least one "page"-kind guard is currently dirty. This is
  // the aggregate signal the sentinel-push effect below reacts to; it must
  // NOT fire just because some unrelated guard (or a modal-kind guard) changed.
  function anyDirtyPageGuard() {
    return guardsRef.current.some(g => g.kind === "page" && g.isDirty);
  }

  // Guard mutations (setGuard/removeGuard) only touch a plain ref, so they
  // never by themselves trigger a re-render of this provider. Bumping this
  // tick -- but only when the aggregate anyDirtyPageGuard() boolean actually
  // flips -- is what makes the provider re-render exactly when page-dirtiness
  // transitions, so the sentinel-push effect (keyed on this tick) reliably
  // re-runs. Without this, a page's isDirty flipping true after mount would
  // never arm the back/forward interception in production.
  const [pageDirtyTick, setPageDirtyTick] = useState(0);
  function bumpPageDirtyTickIfChanged(before: boolean) {
    const after = anyDirtyPageGuard();
    if (before !== after) setPageDirtyTick(t => t + 1);
  }

  const setGuard = useCallback((id: number, handlers: UnsavedChangesGuardHandlers) => {
    const before = anyDirtyPageGuard();
    const existing = findGuard(id);
    if (existing) {
      existing.isDirty = handlers.isDirty;
      existing.onSave = handlers.onSave;
      existing.onDiscard = handlers.onDiscard;
      existing.kind = handlers.kind;
    } else {
      guardsRef.current = [...guardsRef.current, { id, ...handlers }];
    }
    bumpPageDirtyTickIfChanged(before);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [findGuard]);

  const removeGuard = useCallback((id: number) => {
    const before = anyDirtyPageGuard();
    guardsRef.current = guardsRef.current.filter(g => g.id !== id);
    setDialog(current => (current?.guardId === id ? null : current));
    bumpPageDirtyTickIfChanged(before);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      // A download link (typically a blob: URL, e.g. the settings-export
      // feature) is not in-app navigation at all -- let the browser handle
      // it. blob: URLs report their inner origin as `.origin`, so without
      // this bail-out they'd pass the same-origin check below and get
      // wrongly intercepted. Restricting to http(s) protocols is the second
      // half of that same guard (blob:, data:, mailto:, etc. are never
      // in-app route navigation either).
      if (anchor.hasAttribute("download")) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.protocol !== "http:" && url.protocol !== "https:") return;
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

  function activeDirtyPageGuard() {
    const guards = guardsRef.current;
    for (let i = guards.length - 1; i >= 0; i--) {
      if (guards[i].kind === "page" && guards[i].isDirty) return guards[i];
    }
    return null;
  }

  // Ensures one extra history entry sits on top whenever a page guard is dirty,
  // so the next back-press pops that sentinel (caught below) instead of
  // leaving the page. Keyed on pageDirtyTick (bumped only when the aggregate
  // anyDirtyPageGuard() boolean actually flips) so this reliably re-runs
  // whenever a page's dirtiness transitions -- including well after mount,
  // which a dependency-less effect firing only on the PROVIDER's own renders
  // could miss entirely.
  //
  // When dirtiness transitions back to clean, we neutralize (rather than
  // pop) the sentinel via replaceState: popping here would itself fire a
  // popstate and risk interfering with in-flight app navigation, but leaving
  // it in place causes a dead first back-press once the page is clean again
  // (the sentinel silently absorbs it since pushState never changed the
  // visible URL). replaceState swaps the current entry's state without
  // firing popstate, so the leftover sentinel is gone and the next
  // back-press acts on the real underlying history entry.
  useEffect(() => {
    const dirty = anyDirtyPageGuard();
    if (dirty && !sentinelActiveRef.current) {
      const id = ++nextSentinelId;
      sentinelIdRef.current = id;
      window.history.pushState({ __unsavedGuardSentinel: true, __sentinelId: id }, "");
      sentinelActiveRef.current = true;
    } else if (!dirty && sentinelActiveRef.current) {
      window.history.replaceState(null, "");
      sentinelActiveRef.current = false;
      sentinelIdRef.current = null;
    }
  }, [pageDirtyTick]);

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

  const contextValue = useMemo(() => ({ setGuard, removeGuard, requestClose }), [setGuard, removeGuard, requestClose]);

  const handleSaveAndLeave = useCallback(async () => {
    if (!dialog) return;
    const guard = findGuard(dialog.guardId);
    if (!guard) { setDialog(null); return; }
    const dialogAtStart = dialog;
    setDialog(d => (d ? { ...d, saving: true, error: null } : d));
    let ok: boolean;
    try {
      ok = await guard.onSave();
    } catch {
      ok = false;
    }
    if (ok) {
      // The Discard/Cancel buttons stay clickable while a save is in flight
      // (so a hanging onSave can never lock the user out -- see
      // UnsavedChangesDialog), so by the time this resolves the user may
      // have already dismissed this exact dialog some other way. If so,
      // this stale success must be a no-op: dialogRef mirrors the live
      // dialog state, so if it no longer points at the dialog we started
      // with, skip the side effects below rather than double-firing
      // onDiscard/onLeave or reopening a dialog the user already closed.
      if (dialogRef.current?.guardId === dialogAtStart.guardId) {
        // onDiscard runs after BOTH a successful save-and-leave (here) AND a
        // plain discard-and-leave (handleDiscardAndLeave below) -- for a
        // page guard, this means onDiscard must be safe to call regardless
        // of which path led here. The plan's prescribed page-guard pattern
        // (`onDiscard: () => setDraft(serverSnapshot)`) resets to a
        // pre-save snapshot even on the save-succeeded path; that's only
        // correct because every current page-guard consumer navigates away
        // immediately afterward (via dialog.onLeave below) rather than
        // staying on the page to observe the stale reset.
        guard.onDiscard();
        dialogAtStart.onLeave?.();
        setDialog(null);
      }
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
