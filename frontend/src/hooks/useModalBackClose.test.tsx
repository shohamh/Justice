import { StrictMode, useState } from "react";
import { render, renderHook, waitFor, screen, fireEvent } from "@testing-library/react";
import { BrowserRouter, Link, Routes, Route } from "react-router-dom";
import { describe, expect, test, vi, beforeEach } from "vitest";
import { useModalBackClose } from "./useModalBackClose";

function ModalUnderTest({ onClose }: { onClose: () => void }) {
  useModalBackClose(onClose);
  return null;
}

function HandoffHarness({ active, onReplacementClose }: { active: "first" | "replacement"; onReplacementClose: () => void }) {
  return active === "first"
    ? <ModalUnderTest onClose={() => undefined} />
    : <div data-testid="replacement-modal"><ModalUnderTest onClose={onReplacementClose} /></div>;
}

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

  test("keeps a replacement modal open when the previous modal unmounts before deferred cleanup", async () => {
    const onReplacementClose = vi.fn();
    const { rerender } = render(
      <HandoffHarness active="first" onReplacementClose={onReplacementClose} />,
    );
    expect(isOnModalEntry()).toBe(true);

    rerender(<HandoffHarness active="replacement" onReplacementClose={onReplacementClose} />);

    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(document.querySelector("[data-testid='replacement-modal']")).not.toBeNull();
    expect(onReplacementClose).not.toHaveBeenCalled();
    expect(isOnModalEntry()).toBe(true);
  });

  test("does not close the modal immediately due to React StrictMode's dev-only double-invoke of effects", async () => {
    // StrictMode double-invokes effects on mount (mount → cleanup → mount, all
    // synchronously) purely to surface non-idempotent effects. This hook's
    // cleanup calls history.back() when it looks like a real close — under
    // the double-invoke, the *first* (fake) cleanup used to schedule that
    // call synchronously, and by the time it resolved asynchronously the
    // *second* (real) mount's popstate listener was already attached, so it
    // misread the stale back-navigation as a real back-button press and
    // closed the modal that had just opened.
    const onClose = vi.fn();
    const pushSpy = vi.spyOn(window.history, "pushState");

    render(
      <StrictMode>
        <ModalUnderTest onClose={onClose} />
      </StrictMode>,
    );

    // The double-invoke must collapse to a single logical history entry, not
    // stack two — otherwise a single real back-press would only pop one and
    // leave the modal open with a dangling extra entry underneath it.
    expect(pushSpy).toHaveBeenCalledTimes(1);
    expect(isOnModalEntry()).toBe(true);

    // Give the deferred (or, if unfixed, the stale) history.back() every
    // chance to resolve and fire its popstate.
    await new Promise((resolve) => setTimeout(resolve, 100));

    expect(onClose).not.toHaveBeenCalled();
    expect(isOnModalEntry()).toBe(true);
  });

  test("the returned consumeForNavigation() neutralizes the entry synchronously, before any deferred cleanup can race a navigation", () => {
    // NavSheet's items are react-router <Link>s that both close the sheet
    // (onClose) and navigate (Link's own handler) from the same click. The
    // hook's cleanup-time "is this still my entry" check is a best-effort
    // heuristic that can lose a real-world timing race against the Link's
    // own history.pushState (confirmed live: a tap on a nav-sheet item
    // occasionally lands back on the page under the sheet instead of the
    // target route) — a race jsdom's synchronous `act()` flushing can't
    // reproduce, so this asserts the deterministic fix directly: callers
    // that are about to navigate call the returned function *first*, which
    // must strip this hook's own history marker immediately, synchronously,
    // leaving nothing for a later cleanup to mistakenly pop.
    const onClose = vi.fn();
    const { result } = renderHook(() => useModalBackClose(onClose));
    expect(isOnModalEntry()).toBe(true);

    result.current();

    expect(isOnModalEntry()).toBe(false);
  });

  test("after consumeForNavigation(), unmounting never calls history.back() or onClose again", async () => {
    const onClose = vi.fn();
    const { result, unmount } = renderHook(() => useModalBackClose(onClose));
    const lengthAfterConsume = (() => {
      result.current();
      return window.history.length;
    })();

    unmount();
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(window.history.length).toBe(lengthAfterConsume);
    expect(onClose).not.toHaveBeenCalled();
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

  // NavSheet's real items are react-router <Link>s whose onClick prop IS the
  // modal's onClose — a single click both flips `open` to false (this hook's
  // `enabled`) and lets react-router's own Link handler push the target
  // route, in that order, in the same synthetic event. The tests above only
  // exercise the hook via renderHook/unmount or by calling
  // window.history.pushState directly — never through a real <Link> click
  // composed with onClose the way NavSheet actually wires it, under the same
  // StrictMode wrapper production renders under (main.tsx).
  function Sheet({ open, onClose }: { open: boolean; onClose: () => void }) {
    useModalBackClose(onClose, open);
    if (!open) return null;
    return (
      <>
        <button onClick={onClose}>backdrop</button>
        <Link to="/target" onClick={onClose}>go</Link>
      </>
    );
  }

  function Harness() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>open</button>
        <Sheet open={open} onClose={() => setOpen(false)} />
        <Routes>
          <Route path="/" element={<div>home</div>} />
          <Route path="/target" element={<div>target</div>} />
        </Routes>
      </>
    );
  }

  test("clicking a Link item navigates to its target instead of bouncing back to the page under the sheet", async () => {
    render(
      <StrictMode>
        <BrowserRouter>
          <Harness />
        </BrowserRouter>
      </StrictMode>,
    );

    fireEvent.click(screen.getByText("open"));
    fireEvent.click(screen.getByText("go"));

    await waitFor(() => expect(screen.getByText("target")).toBeInTheDocument());
    // Give any deferred/mistaken history.back() from the sheet's own cleanup
    // every chance to fire and undo the navigation before asserting it holds.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(screen.getByText("target")).toBeInTheDocument();
    expect(location.pathname).toBe("/target");
  });

  test("still navigates correctly after an earlier open/close-via-backdrop cycle", async () => {
    // Mirrors a real user opening the nav sheet, dismissing it without
    // navigating (tap outside, X button), then reopening it and picking an
    // item — a very ordinary sequence on a phone. Residual state left behind
    // by the first (non-navigating) close cycle must not corrupt the second.
    render(
      <StrictMode>
        <BrowserRouter>
          <Harness />
        </BrowserRouter>
      </StrictMode>,
    );

    fireEvent.click(screen.getByText("open"));
    fireEvent.click(screen.getByText("backdrop"));
    await waitFor(() => expect(screen.queryByText("go")).not.toBeInTheDocument());

    fireEvent.click(screen.getByText("open"));
    fireEvent.click(screen.getByText("go"));

    await waitFor(() => expect(screen.getByText("target")).toBeInTheDocument());
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(screen.getByText("target")).toBeInTheDocument();
    expect(location.pathname).toBe("/target");
  });
});

describe("useModalBackClose — nested modals", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  function Child({ onClose }: { onClose: () => void }) {
    useModalBackClose(onClose);
    return null;
  }

  function delay(ms: number): Promise<void> {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, ms);
    return promise;
  }
  // Mirrors LocationFormModal inside ShiftFormModal: both modals use the
  // hook, the child is mounted on top of the parent, and closing the child
  // via its X button unmounts it — whose cleanup defers a history.back()
  // that pops the CHILD's entry and fires a global popstate while the
  // parent's own entry is current again.
  function Harness() {
    const [childOpen, setChildOpen] = useState(true);
    const [parentClosed, setParentClosed] = useState(false);
    useModalBackClose(() => setParentClosed(true));
    return (
      <>
        {parentClosed ? (
          <div data-testid="parent-closed" />
        ) : (
          <div data-testid="parent-open" />
        )}
        {childOpen && (
          <>
            <Child onClose={() => setChildOpen(false)} />
            <button onClick={() => setChildOpen(false)}>close-child</button>
          </>
        )}
      </>
    );
  }

  test("closing a nested modal does not close the parent via its cleanup's popstate", async () => {
    render(
      <StrictMode>
        <Harness />
      </StrictMode>,
    );

    expect(screen.getByTestId("parent-open")).toBeInTheDocument();

    // Close the child the way an X button would. The child's cleanup defers
    // history.back(); that back lands on the PARENT's entry and fires a
    // popstate — which must not be mistaken for a back-press targeting the
    // parent.
    fireEvent.click(screen.getByText("close-child"));
    await waitFor(() =>
      expect(screen.queryByText("close-child")).not.toBeInTheDocument(),
    );
    // Give the deferred back() and its popstate every chance to land.
    await delay(50);

    expect(screen.getByTestId("parent-open")).toBeInTheDocument();
    // The parent still owns the current history entry (its marker survived).
    expect(isOnModalEntry()).toBe(true);

    // A genuine second back-press now closes the parent.
    goBack();
    await waitFor(() =>
      expect(screen.getByTestId("parent-closed")).toBeInTheDocument(),
    );
  });

  test("browser back with a nested modal open closes only the child", async () => {
    render(
      <StrictMode>
        <Harness />
      </StrictMode>,
    );

    goBack();
    await waitFor(() =>
      expect(screen.queryByText("close-child")).not.toBeInTheDocument(),
    );
    await delay(50);

    // The pop popped the CHILD's entry onto the parent's; the child closed
    // via its own popstate, and the parent must stay open.
    expect(screen.getByTestId("parent-open")).toBeInTheDocument();
  });
});
