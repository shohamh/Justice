import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, test, vi, beforeEach } from "vitest";
import { useModalBackClose } from "./useModalBackClose";

// jsdom's history.back() applies the navigation and fires popstate
// asynchronously, same as a real browser — tests that trigger it must wait
// for the resulting state change rather than asserting immediately after.
function goBack() {
  window.history.back();
}

// history.length is a total entry count that never decreases on back() (in
// jsdom or real browsers) — only pushing past a rewound point truncates it.
// So "did back() run" is asserted via history.state (our `__modal` marker),
// not length.
function isOnModalEntry() {
  return (window.history.state as { __modal?: boolean } | null)?.__modal === true;
}

describe("useModalBackClose", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  test("pushes a history entry on mount", () => {
    const onClose = vi.fn();
    renderHook(() => useModalBackClose(onClose));
    expect(isOnModalEntry()).toBe(true);
  });

  test("calls onClose when the browser back button fires popstate", async () => {
    const onClose = vi.fn();
    renderHook(() => useModalBackClose(onClose));

    goBack();

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  test("consumes its own history entry on unmount when closed some other way", async () => {
    const onClose = vi.fn();
    const { unmount } = renderHook(() => useModalBackClose(onClose));
    expect(isOnModalEntry()).toBe(true);

    unmount();

    // history.back() delivers its state change / popstate asynchronously,
    // same as a real browser.
    await waitFor(() => expect(isOnModalEntry()).toBe(false));
    // Unmounting via "closed some other way" must not itself re-trigger onClose.
    expect(onClose).not.toHaveBeenCalled();
  });

  test("does not call history.back() again on unmount after popstate already closed it", async () => {
    const onClose = vi.fn();
    const { unmount } = renderHook(() => useModalBackClose(onClose));
    expect(isOnModalEntry()).toBe(true);

    goBack();
    await waitFor(() => expect(isOnModalEntry()).toBe(false));

    const lengthBeforeUnmount = window.history.length;
    unmount();

    // No extra history.back() call should fire past the entry popstate already consumed.
    expect(window.history.length).toBe(lengthBeforeUnmount);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test("always calls the latest onClose without re-pushing history on re-render", async () => {
    const onCloseA = vi.fn();
    const onCloseB = vi.fn();
    const { rerender } = renderHook(({ onClose }) => useModalBackClose(onClose), {
      initialProps: { onClose: onCloseA },
    });
    const lengthAfterMount = window.history.length;

    rerender({ onClose: onCloseB });
    // A new inline callback each render (the common case: onClose={() => setOpen(false)})
    // must not push another history entry.
    expect(window.history.length).toBe(lengthAfterMount);

    goBack();

    await waitFor(() => expect(onCloseB).toHaveBeenCalledTimes(1));
    expect(onCloseA).not.toHaveBeenCalled();
  });

  test("does not consume a newer history entry pushed by something else while open", async () => {
    // Simulates HeaderSearch: selecting a result calls navigate() (pushing a
    // new entry) and then closes the panel in the same handler. The hook's
    // cleanup must not blindly call history.back() in that case — its own
    // entry is no longer on top, so back() would undo the navigation instead.
    const onClose = vi.fn();
    const { unmount } = renderHook(() => useModalBackClose(onClose));
    expect(isOnModalEntry()).toBe(true);

    window.history.pushState(null, "", "/somewhere-else");

    unmount();

    // A buggy cleanup calling history.back() here applies asynchronously
    // (see the file-level comment on goBack()) — waitFor() would resolve
    // the instant it first observes the correct pathname, before that async
    // reversion has a chance to land, masking the bug. Wait out a real tick
    // instead, then assert the navigation is still intact.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(location.pathname).toBe("/somewhere-else");
  });

  test("enabled=false keeps the hook inert, for always-mounted components gated on their own `open` prop", () => {
    const onClose = vi.fn();
    renderHook(() => useModalBackClose(onClose, false));
    expect(isOnModalEntry()).toBe(false);
  });

  test("pushes when enabled flips to true, and pops when it flips back to false", async () => {
    const onClose = vi.fn();
    const { rerender } = renderHook(({ open }) => useModalBackClose(onClose, open), {
      initialProps: { open: false },
    });
    expect(isOnModalEntry()).toBe(false);

    rerender({ open: true });
    expect(isOnModalEntry()).toBe(true);

    rerender({ open: false });
    await waitFor(() => expect(isOnModalEntry()).toBe(false));
    expect(onClose).not.toHaveBeenCalled();
  });
});
