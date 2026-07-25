import { useEffect, useRef } from "react";

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
 */
export function useModalBackClose(onClose: () => void, enabled = true): void {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!enabled) return;

    let ownEntryOnTop = true;
    window.history.pushState({ __modal: true }, "");

    function handlePopState() {
      ownEntryOnTop = false;
      onCloseRef.current();
    }

    window.addEventListener("popstate", handlePopState);

    return () => {
      window.removeEventListener("popstate", handlePopState);
      if (ownEntryOnTop) {
        window.history.back();
      }
    };
  }, [enabled]);
}
