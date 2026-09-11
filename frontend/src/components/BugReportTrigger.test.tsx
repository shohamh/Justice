import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import BugReportTrigger from "./BugReportTrigger";
import { BugReportModalProvider } from "../contexts/BugReportModalContext";
import { snapdom } from "@zumer/snapdom";
import { reportFrontendError } from "../errorReporting";

function fakeCanvas(dataUrl: string): HTMLCanvasElement {
  return { toDataURL: vi.fn(() => dataUrl) } as unknown as HTMLCanvasElement;
}

vi.mock("@zumer/snapdom", () => ({
  snapdom: { toCanvas: vi.fn().mockResolvedValue(fakeCanvas("data:image/png;base64,AAA")) },
}));
vi.mock("../errorReporting", () => ({ reportFrontendError: vi.fn() }));
vi.mock("../hooks/useNavigationHistory", () => ({ useNavigationHistory: () => [] }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ loggedIn: true }) }));
vi.mock("../api/bugReports", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/bugReports")>()),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
}));

function renderTrigger() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <BugReportModalProvider>
          <BugReportTrigger />
        </BugReportModalProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("BugReportTrigger", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("opens the modal immediately with a screenshot-pending placeholder, usable before capture resolves", async () => {
    let releaseCapture: (canvas: HTMLCanvasElement) => void = () => {};
    vi.mocked(snapdom.toCanvas).mockReturnValueOnce(
      new Promise((resolve) => { releaseCapture = resolve; }),
    );

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    // Modal opens right away — usable immediately instead of making the user
    // wait out a capture that can take tens of seconds on a heavy page.
    expect(await screen.findByTestId("bug-report-modal-overlay")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-screenshot-loading")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-description")).not.toBeDisabled();
    expect(screen.getByTestId("bug-report-submit")).toBeInTheDocument();

    await waitFor(() => expect(snapdom.toCanvas).toHaveBeenCalled());
    const [, options] = vi.mocked(snapdom.toCanvas).mock.calls[0];
    expect(options).toEqual({ dpr: 1 });

    releaseCapture(fakeCanvas("data:image/png;base64,AAA"));

    await waitFor(() => expect(screen.queryByTestId("bug-report-screenshot-loading")).not.toBeInTheDocument());
    expect(screen.getByAltText("")).toHaveAttribute("src", "data:image/png;base64,AAA");
  });

  test("preserves text typed while capture is still pending, once it resolves", async () => {
    // The modal doesn't remount when the screenshot arrives (same React key,
    // keyed by the open's token) — this locks that in, since it's the whole
    // point of opening the modal before capture finishes.
    let releaseCapture: (canvas: HTMLCanvasElement) => void = () => {};
    vi.mocked(snapdom.toCanvas).mockReturnValueOnce(
      new Promise((resolve) => { releaseCapture = resolve; }),
    );

    renderTrigger();
    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await screen.findByTestId("bug-report-screenshot-loading");
    fireEvent.change(screen.getByTestId("bug-report-description"), { target: { value: "typed while pending" } });

    releaseCapture(fakeCanvas("data:image/png;base64,AAA"));

    await waitFor(() => expect(screen.getByAltText("")).toHaveAttribute("src", "data:image/png;base64,AAA"));
    expect(screen.getByTestId("bug-report-description")).toHaveValue("typed while pending");
  });

  test("never passes a clip option, and keeps the capture host off-screen", async () => {
    // Multiple live-verified attempts at snapdom's offscreen-subtree pruning
    // (a manual clip rect, `clip: 'viewport'` alone, `clip: 'viewport'` +
    // `reconcile: true`) each silently dropped real, currently-visible content
    // in a different place on the actual duty calendar (FullCalendar's dense
    // day-grid). Omitting `clip` entirely is the one option confirmed correct
    // on every part of the live page — it's checked as `if (e.clip && ...)`
    // inside snapdom's own walk, so without it nothing gets pruned. The host
    // stays off-screen (translateX) since there's no clip-viewport resolution
    // to keep it on-screen for.
    let releaseCapture: (canvas: HTMLCanvasElement) => void = () => {};
    vi.mocked(snapdom.toCanvas).mockReturnValueOnce(
      new Promise((resolve) => { releaseCapture = resolve; }),
    );

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await waitFor(() => expect(snapdom.toCanvas).toHaveBeenCalled());
    const host = document.body.querySelector<HTMLElement>("[data-bug-report-capture-host]");
    expect(host?.style.transform).toBe("translateX(-100000px)");

    releaseCapture(fakeCanvas("data:image/png;base64,AAA"));
  });

  test("excludes the bug-report modal itself from the capture clone", async () => {
    // Capture now runs in the background while the modal is already open, so
    // without this the modal (its overlay, form, "capturing..." placeholder)
    // would show up inside its own screenshot.
    let capturedNode: HTMLElement | null = null;
    let releaseCapture: (canvas: HTMLCanvasElement) => void = () => {};
    vi.mocked(snapdom.toCanvas).mockImplementationOnce((node) => {
      capturedNode = node as HTMLElement;
      return new Promise((resolve) => { releaseCapture = resolve; });
    });

    renderTrigger();
    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await screen.findByTestId("bug-report-modal-overlay");
    await waitFor(() => expect(snapdom.toCanvas).toHaveBeenCalled());

    expect(capturedNode?.querySelector("[data-bug-report-capture-exclude]")).toBeNull();
    // Sanity: only the clone excludes it — the live modal is still open.
    expect(document.body.querySelector("[data-bug-report-capture-exclude]")).not.toBeNull();

    releaseCapture(fakeCanvas("data:image/png;base64,AAA"));
  });

  test("exports the rasterized capture as a real PNG data URL, not SVG", async () => {
    const canvas = fakeCanvas("data:image/png;base64,AAA");
    vi.mocked(snapdom.toCanvas).mockResolvedValueOnce(canvas);

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await waitFor(() => expect(canvas.toDataURL).toHaveBeenCalledWith("image/png"));
    expect(screen.getByAltText("")).toHaveAttribute("src", expect.stringMatching(/^data:image\/png;base64,/));
  });

  test("shows the fallback message once capture fails (non-fatal), not immediately on open", async () => {
    let rejectCapture: (err: Error) => void = () => {};
    vi.mocked(snapdom.toCanvas).mockReturnValueOnce(
      new Promise((_resolve, reject) => { rejectCapture = reject; }),
    );

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await screen.findByTestId("bug-report-modal-overlay");
    expect(screen.getByTestId("bug-report-screenshot-loading")).toBeInTheDocument();
    expect(screen.queryByText("לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו")).not.toBeInTheDocument();

    await waitFor(() => expect(snapdom.toCanvas).toHaveBeenCalled());
    rejectCapture(new Error("capture failed"));

    await waitFor(() =>
      expect(screen.getByText("לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו")).toBeInTheDocument(),
    );
    expect(reportFrontendError).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "bug-report-capture-failed", message: "capture failed" }),
    );
  });

  test("falls back to the fallback message if capture hangs past the timeout", async () => {
    vi.useFakeTimers();
    // A promise that never settles on its own — simulates toCanvas() hanging
    // instead of rejecting, which a plain try/catch around toCanvas() would
    // never recover from.
    vi.mocked(snapdom.toCanvas).mockReturnValueOnce(new Promise(() => {}));

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByTestId("bug-report-screenshot-loading")).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(45100); });

    expect(screen.queryByTestId("bug-report-screenshot-loading")).not.toBeInTheDocument();
    expect(screen.getByText("לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו")).toBeInTheDocument();
    expect(reportFrontendError).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "bug-report-capture-failed",
        message: "screenshot capture timed out",
        duration_ms: expect.any(Number),
      }),
    );

    vi.useRealTimers();
  });

  test("starts capture on mousedown, before a document-level outside-click listener can close another panel", async () => {
    // Simulates a panel (e.g. the notifications dropdown) that closes itself
    // via a document-level mousedown listener, as NotificationBell does.
    const outsideClickHandler = vi.fn();
    document.addEventListener("mousedown", outsideClickHandler);

    renderTrigger();

    await act(async () => { fireEvent.mouseDown(screen.getByTestId("bug-report-trigger")); });

    // Our own mousedown handler (bound directly on the button) must run
    // before the event bubbles up to trigger document-level listeners.
    await waitFor(() => expect(snapdom.toCanvas).toHaveBeenCalled());
    expect(outsideClickHandler).toHaveBeenCalled();

    document.removeEventListener("mousedown", outsideClickHandler);
  });

  test("translates only a capture clone while live app scroll content remains unchanged", async () => {
    const header = document.createElement("header");
    header.style.transform = "scale(1)";
    const appScrollContainer = document.createElement("main");
    appScrollContainer.dataset.bugReportScrollContainer = "";
    Object.defineProperties(appScrollContainer, {
      scrollTop: { value: 300, configurable: true },
      scrollLeft: { value: 40, configurable: true },
    });
    const appScrollContent = document.createElement("div");
    appScrollContent.dataset.bugReportScrollContent = "";
    appScrollContent.style.transform = "scale(1)";
    appScrollContainer.append(appScrollContent);
    document.body.append(header);
    document.body.append(appScrollContainer);

    try {
      let capturedNode: HTMLElement | null = null;
      let releaseCapture: (canvas: HTMLCanvasElement) => void = () => {};
      vi.mocked(snapdom.toCanvas).mockImplementationOnce((node) => {
        capturedNode = node as HTMLElement;
        return new Promise((resolve) => { releaseCapture = resolve; });
      });
      renderTrigger();

      fireEvent.click(screen.getByTestId("bug-report-trigger"));

      await waitFor(() => expect(snapdom.toCanvas).toHaveBeenCalled());
      expect(capturedNode).not.toBe(document.body);
      expect(capturedNode?.querySelector<HTMLElement>("[data-bug-report-scroll-content]")?.style.transform)
        .toBe("translate(-40px, -300px)");
      expect(capturedNode?.querySelector<HTMLElement>("header")?.style.transform).toBe("scale(1)");
      // The app-shell branch shifts the scroll content, not the capture root itself.
      expect(capturedNode?.style.transform).toBe("");
      expect(appScrollContent.style.transform).toBe("scale(1)");
      expect(appScrollContainer.scrollTop).toBe(300);
      expect(appScrollContainer.scrollLeft).toBe(40);
      expect(capturedNode?.isConnected).toBe(true);

      releaseCapture(fakeCanvas("data:image/png;base64,AAA"));
      await waitFor(() => expect(capturedNode?.isConnected).toBe(false));
    } finally {
      header.remove();
      appScrollContainer.remove();
    }
  });

  test("falls back to window scroll when the app shell is absent", async () => {
    Object.defineProperty(window, "scrollX", { value: 40, configurable: true });
    Object.defineProperty(window, "scrollY", { value: 300, configurable: true });

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await waitFor(() => expect(snapdom.toCanvas).toHaveBeenCalled());
    const [captureNode] = vi.mocked(snapdom.toCanvas).mock.calls[0];
    expect(captureNode).not.toBe(document.body);
    expect((captureNode as HTMLElement).style.transform).toBe("translate(-40px, -300px)");

    Object.defineProperty(window, "scrollX", { value: 0, configurable: true });
    Object.defineProperty(window, "scrollY", { value: 0, configurable: true });
  });

  test("shows a badge with the unseen-activity count", async () => {
    const { getMyBugReportsUnseenCount } = await import("../api/bugReports");
    vi.mocked(getMyBugReportsUnseenCount).mockResolvedValue({ count: 3 });

    renderTrigger();

    expect(await screen.findByTestId("bug-report-trigger-badge")).toHaveTextContent("3");
  });

  test("shows no badge when there is no unseen activity", async () => {
    renderTrigger();

    await waitFor(() => expect(screen.queryByTestId("bug-report-trigger")).toBeInTheDocument());
    expect(screen.queryByTestId("bug-report-trigger-badge")).not.toBeInTheDocument();
  });
});
