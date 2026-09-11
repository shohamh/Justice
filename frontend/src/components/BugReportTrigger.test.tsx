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

  test("captures a screenshot of the page BEFORE opening the modal, then opens it", async () => {
    let releaseCapture: (canvas: HTMLCanvasElement) => void = () => {};
    vi.mocked(snapdom.toCanvas).mockReturnValueOnce(
      new Promise((resolve) => { releaseCapture = resolve; }),
    );

    renderTrigger();

    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).toBeNull();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    // The spinner must be showing (i.e. painted) before the heavy capture work
    // (which briefly blocks the main thread) begins.
    expect(screen.getByTestId("bug-report-trigger-spinner")).toBeInTheDocument();
    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).toBeNull();

    // toCanvas must be called against a capture-only representation while the
    // modal (and its dimming overlay) is still absent.
    await waitFor(() => expect(snapdom.toCanvas).toHaveBeenCalled());
    const [captureNode, options] = vi.mocked(snapdom.toCanvas).mock.calls[0];
    expect(captureNode).not.toBe(document.body);
    expect(options).toEqual(expect.objectContaining({ dpr: 1 }));
    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).toBeNull();

    releaseCapture(fakeCanvas("data:image/png;base64,AAA"));

    await waitFor(() =>
      expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).not.toBeNull(),
    );
  });

  test("passes the captured screenshot down to the modal", async () => {
    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await waitFor(() => expect(screen.getByAltText("")).toHaveAttribute("src", "data:image/png;base64,AAA"));
  });

  test("exports the rasterized capture as a real PNG data URL, not SVG", async () => {
    const canvas = fakeCanvas("data:image/png;base64,AAA");
    vi.mocked(snapdom.toCanvas).mockResolvedValueOnce(canvas);

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await waitFor(() => expect(canvas.toDataURL).toHaveBeenCalledWith("image/png"));
    expect(screen.getByAltText("")).toHaveAttribute("src", expect.stringMatching(/^data:image\/png;base64,/));
  });

  test("still opens the modal with a null screenshot when capture fails (non-fatal)", async () => {
    vi.mocked(snapdom.toCanvas).mockRejectedValueOnce(new Error("capture failed"));

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await waitFor(() =>
      expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).not.toBeNull(),
    );
    expect(screen.getByText("לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו")).toBeInTheDocument();
    expect(reportFrontendError).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "bug-report-capture-failed", message: "capture failed" }),
    );
  });

  test("shows a spinner on the trigger while capturing, and disables it", async () => {
    let releaseCapture: (canvas: HTMLCanvasElement) => void = () => {};
    vi.mocked(snapdom.toCanvas).mockReturnValueOnce(
      new Promise((resolve) => { releaseCapture = resolve; }),
    );

    renderTrigger();

    const trigger = screen.getByTestId("bug-report-trigger");
    fireEvent.click(trigger);

    expect(trigger).toBeDisabled();
    expect(screen.getByTestId("bug-report-trigger-spinner")).toBeInTheDocument();

    releaseCapture(fakeCanvas("data:image/png;base64,AAA"));

    await waitFor(() => expect(trigger).not.toBeDisabled());
    expect(screen.queryByTestId("bug-report-trigger-spinner")).not.toBeInTheDocument();
  });

  test("gives up and opens the modal without a screenshot if capture hangs past the timeout", async () => {
    vi.useFakeTimers();
    // A promise that never settles on its own — simulates toCanvas() hanging
    // (e.g. inlining large images on a content-heavy page) instead of
    // rejecting, which a plain try/catch around toCanvas() would never recover from.
    vi.mocked(snapdom.toCanvas).mockReturnValueOnce(new Promise(() => {}));

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));
    expect(screen.getByTestId("bug-report-trigger")).toBeDisabled();

    // Advance past the capture timeout, plus the small rAF/setTimeout yield
    // that now happens before capture starts.
    await act(async () => { await vi.advanceTimersByTimeAsync(6100); });

    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).not.toBeNull();
    expect(screen.getByText("לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-trigger")).not.toBeDisabled();
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
