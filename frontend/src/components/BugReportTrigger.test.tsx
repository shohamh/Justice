import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import BugReportTrigger from "./BugReportTrigger";
import { BugReportModalProvider } from "../contexts/BugReportModalContext";
import { toPng } from "html-to-image";

vi.mock("html-to-image", () => ({ toPng: vi.fn().mockResolvedValue("data:image/png;base64,AAA") }));
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
    let releaseCapture: (url: string) => void = () => {};
    vi.mocked(toPng).mockReturnValueOnce(
      new Promise((resolve) => { releaseCapture = resolve; }),
    );

    renderTrigger();

    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).toBeNull();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    // The spinner must be showing (i.e. painted) before the heavy capture work
    // (which briefly blocks the main thread) begins.
    expect(screen.getByTestId("bug-report-trigger-spinner")).toBeInTheDocument();
    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).toBeNull();

    // toPng must be called against a capture-only representation while the
    // modal (and its dimming overlay) is still absent.
    await waitFor(() => expect(toPng).toHaveBeenCalled());
    const [captureNode, options] = vi.mocked(toPng).mock.calls[0];
    expect(captureNode).not.toBe(document.body);
    expect(options).toEqual(expect.objectContaining({ pixelRatio: 1 }));
    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).toBeNull();

    releaseCapture("data:image/png;base64,AAA");

    await waitFor(() =>
      expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).not.toBeNull(),
    );
  });

  test("passes the captured screenshot down to the modal", async () => {
    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await waitFor(() => expect(screen.getByAltText("")).toHaveAttribute("src", "data:image/png;base64,AAA"));
  });

  test("still opens the modal with a null screenshot when capture fails (non-fatal)", async () => {
    vi.mocked(toPng).mockRejectedValueOnce(new Error("capture failed"));

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await waitFor(() =>
      expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).not.toBeNull(),
    );
    expect(screen.getByText("לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו")).toBeInTheDocument();
  });

  test("shows a spinner on the trigger while capturing, and disables it", async () => {
    let releaseCapture: (url: string) => void = () => {};
    vi.mocked(toPng).mockReturnValueOnce(
      new Promise((resolve) => { releaseCapture = resolve; }),
    );

    renderTrigger();

    const trigger = screen.getByTestId("bug-report-trigger");
    fireEvent.click(trigger);

    expect(trigger).toBeDisabled();
    expect(screen.getByTestId("bug-report-trigger-spinner")).toBeInTheDocument();

    releaseCapture("data:image/png;base64,AAA");

    await waitFor(() => expect(trigger).not.toBeDisabled());
    expect(screen.queryByTestId("bug-report-trigger-spinner")).not.toBeInTheDocument();
  });

  test("gives up and opens the modal without a screenshot if capture hangs past the timeout", async () => {
    vi.useFakeTimers();
    // A promise that never settles on its own — simulates toPng() hanging
    // (e.g. inlining large fonts/images on a content-heavy page) instead of
    // rejecting, which a plain try/catch around toPng() would never recover from.
    vi.mocked(toPng).mockReturnValueOnce(new Promise(() => {}));

    renderTrigger();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));
    expect(screen.getByTestId("bug-report-trigger")).toBeDisabled();

    // Advance past the capture timeout, plus the small rAF/setTimeout yield
    // that now happens before capture starts.
    await act(async () => { await vi.advanceTimersByTimeAsync(6100); });

    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).not.toBeNull();
    expect(screen.getByText("לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-trigger")).not.toBeDisabled();

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
    await waitFor(() => expect(toPng).toHaveBeenCalled());
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
      let releaseCapture: (url: string) => void = () => {};
      vi.mocked(toPng).mockImplementationOnce((node) => {
        capturedNode = node as HTMLElement;
        return new Promise((resolve) => { releaseCapture = resolve; });
      });
      renderTrigger();

      fireEvent.click(screen.getByTestId("bug-report-trigger"));

      await waitFor(() => expect(toPng).toHaveBeenCalled());
      expect(capturedNode).not.toBe(document.body);
      expect(capturedNode?.querySelector<HTMLElement>("[data-bug-report-scroll-content]")?.style.transform)
        .toBe("translate(-40px, -300px)");
      expect(capturedNode?.querySelector<HTMLElement>("header")?.style.transform).toBe("scale(1)");
      expect(appScrollContent.style.transform).toBe("scale(1)");
      expect(appScrollContainer.scrollTop).toBe(300);
      expect(appScrollContainer.scrollLeft).toBe(40);
      expect(capturedNode?.isConnected).toBe(true);

      releaseCapture("data:image/png;base64,AAA");
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

    await waitFor(() => expect(toPng).toHaveBeenCalled());
    const [captureNode, options] = vi.mocked(toPng).mock.calls[0];
    expect(captureNode).not.toBe(document.body);
    expect(options).toEqual(expect.objectContaining({
      style: expect.objectContaining({ transform: "translate(-40px, -300px)" }),
    }));

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
