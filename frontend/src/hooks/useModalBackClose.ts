import { useEffect, useRef } from "react";

type ModalHistoryState = { __modal?: boolean; __modalId?: number };
type PendingBack = { cancelled: boolean; entryId: number };

let nextModalEntryId = 0;

/**
 * Makes the mobile/browser back button (or gesture) close an open modal
 * instead of navigating the app away.
 *
 * Two call shapes, matching the two mounting patterns used in this app:
 * - Most modals are only mounted while open (e.g.
 *   `{open && <SomeModal onClose={...} />}`) — call this unconditionally
 *   from inside the modal with just `useModalBackClose(onClose)`; the
 *   component's mount lifecycle already matches the modal's open lifecycle.
 * - A few components (e.g. NavSheet) stay mounted and gate their own
 *   visibility on an `open` prop internally (often via an early
 *   `if (!open) return null`) — call `useModalBackClose(onClose, open)`
 *   *before* that early return, so the hook still runs on every render
 *   (satisfying the rules of hooks) but its effect only activates while
 *   `open` is true.
 *
 * While active, pushes one history entry; a back press pops it and triggers
 * onClose instead of leaving the page. If the modal closes some other way (X
 * button, backdrop click, Escape, successful submit) while our entry is still
 * on top, cleanup consumes it via history.back() so the back-stack doesn't
 * accumulate a stale entry a later back-press would otherwise hit.
 *
 * That cleanup's history.back() is deferred to a microtask rather than
 * called synchronously, and a fresh mount cancels any deferral still
 * pending. This matters because React's StrictMode double-invokes effects
 * on mount in dev (mount → cleanup → mount, all synchronously) specifically
 * to surface effects like this one that touch non-idempotent external
 * state. Without the deferral, the *first* (fake) cleanup's history.back()
 * would resolve asynchronously after the *second* (real) mount had already
 * attached its own popstate listener — which would misread that stale
 * back-navigation as a genuine back-button press and close the modal
 * immediately after it opened. Deferring to a microtask (rather than
 * e.g. setTimeout) lets the second mount — which React runs synchronously,
 * before any microtask can flush — cancel the first cleanup's scheduled
 * back() and reuse its still-current history entry instead of pushing a
 * duplicate one; a macrotask would also work for that, but would resolve at
 * an arbitrary point relative to a caller's own fake-timer usage instead of
 * within the same microtask-flush every `await` already performs.
 *
 * The pending-back token above is deliberately kept in a ref scoped to
 * *this* hook call, not a single module-level slot: with a nested modal
 * (parent and child both call this hook), React runs both instances'
 * StrictMode fake-mount → cleanup → real-mount in one synchronous batch,
 * tree-order (child's effects before its parent's, for both mount and
 * cleanup). By the time the child's fake cleanup runs, the parent has
 * already pushed its own fake entry on top, so the child's "is my entry
 * still current" check fails and it correctly does nothing — but the
 * parent's fake cleanup *does* still see its own entry on top and defers a
 * back() for it. A single shared slot would then have the child's
 * following real mount see that leftover token, match it against the
 * current (parent's) history state, and wrongly adopt the parent's entry
 * as its own — leaving the child and parent's `entryIdRef`s pointing at
 * the same id and silently swapping which one a later back-press closes.
 * Scoping the slot per hook call (a ref, stable across the same
 * mount/cleanup/remount cycle since StrictMode reuses the fiber) makes
 * that adoption impossible between different instances.
 *
 * Returns `consumeForNavigation()` — call it synchronously, *before*
 * triggering a navigation that will also close the modal (e.g. a nav-sheet
 * `<Link>` whose `onClick` both closes the sheet and routes elsewhere).
 * It strips this hook's marker off the current history entry immediately,
 * so there's nothing left for the close-triggered cleanup above to
 * mistakenly `history.back()` later, whenever it happens to run relative to
 * the navigation's own `pushState`. Confirmed live (not reproducible in
 * jsdom, where Testing Library's `act()` flushes effects synchronously
 * around each event and closes the timing gap a real browser leaves open):
 * tapping a nav-sheet item occasionally landed back on the page under the
 * sheet instead of the tapped destination, because the cleanup's
 * "is my entry still on top" check raced the `<Link>`'s own history push.
 */
export function useModalBackClose(onClose: () => void, enabled = true): () => void {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const entryIdRef = useRef<number | null>(null);
  const consumedRef = useRef(false);
  const pendingBackRef = useRef<PendingBack | null>(null);

  useEffect(() => {
    if (!enabled) return;
    consumedRef.current = false;

    let ownEntryOnTop = true;
    const currentState = window.history.state as ModalHistoryState | null;
    const myPendingBack = pendingBackRef.current;

    if (myPendingBack !== null && currentState?.__modalId === myPendingBack.entryId) {
      // A StrictMode double-invoke: the immediately-preceding cleanup's
      // deferred back() (for THIS SAME hook call — see the ref-scoping note
      // above) is still pending. Cancel it and keep using its entry instead
      // of pushing a second one.
      entryIdRef.current = myPendingBack.entryId;
      myPendingBack.cancelled = true;
      pendingBackRef.current = null;
    } else {
      // A pending cleanup can become stale if another history entry was
      // pushed before its microtask ran. It must never consume that newer
      // entry.
      if (myPendingBack !== null) myPendingBack.cancelled = true;
      pendingBackRef.current = null;
      const entryId = ++nextModalEntryId;
      entryIdRef.current = entryId;
      window.history.pushState({ __modal: true, __modalId: entryId }, "");
    }
    function handlePopState() {
      // A nested modal pushed its own entry on top of ours; when it closes,
      // its cleanup's history.back() pops that entry and lands back on OUR
      // entry. That popstate isn't a back-press targeting this modal — the
      // current entry still being our own proves it — so don't close.
      const state = window.history.state as ModalHistoryState | null;
      if (state?.__modalId === entryIdRef.current) return;
      ownEntryOnTop = false;
      onCloseRef.current();
    }

    window.addEventListener("popstate", handlePopState);

    return () => {
      window.removeEventListener("popstate", handlePopState);
      // consumeForNavigation() already neutralized our entry synchronously —
      // nothing left to do, and no timing-sensitive check needed.
      if (consumedRef.current) return;
      // Only consume our own entry if it's still the current one. If
      // something else pushed a new entry while we were open (e.g. a search
      // result's navigate() call, closing the panel in the same handler),
      // our entry is no longer on top — calling back() here would undo that
      // navigation instead of popping our own state.
      const stillOnOwnEntry = (window.history.state as ModalHistoryState | null)?.__modalId === entryIdRef.current;
      if (ownEntryOnTop && stillOnOwnEntry) {
        const token: PendingBack = { cancelled: false, entryId: entryIdRef.current! };
        pendingBackRef.current = token;
        queueMicrotask(() => {
          if (token.cancelled || pendingBackRef.current !== token) return;
          pendingBackRef.current = null;
          if ((window.history.state as ModalHistoryState | null)?.__modalId !== entryIdRef.current) return;
          window.history.back();
        });
      }
    };
  }, [enabled]);

  return function consumeForNavigation() {
    if (entryIdRef.current === null || consumedRef.current) return;
    consumedRef.current = true;
    const current = window.history.state as ModalHistoryState | null;
    if (current?.__modalId === entryIdRef.current) {
      window.history.replaceState(null, "");
    }
  };
}
