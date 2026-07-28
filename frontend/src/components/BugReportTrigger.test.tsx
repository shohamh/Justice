import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import BugReportTrigger from "./BugReportTrigger";
import { toPng } from "html-to-image";

vi.mock("html-to-image", () => ({ toPng: vi.fn().mockResolvedValue("data:image/png;base64,AAA") }));
vi.mock("../hooks/useNavigationHistory", () => ({ useNavigationHistory: () => [] }));

describe("BugReportTrigger", () => {
  test("captures a screenshot of the page BEFORE opening the modal, then opens it", async () => {
    render(
      <MemoryRouter>
        <BugReportTrigger />
      </MemoryRouter>,
    );

    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).toBeNull();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    // toPng must be called against document.body while the modal is still absent —
    // i.e. the capture happens before the modal (and its dimming overlay) mounts.
    expect(toPng).toHaveBeenCalledWith(document.body, expect.objectContaining({ pixelRatio: 1 }));
    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).toBeNull();

    await waitFor(() =>
      expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).not.toBeNull(),
    );
  });

  test("passes the captured screenshot down to the modal", async () => {
    render(
      <MemoryRouter>
        <BugReportTrigger />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await waitFor(() => expect(screen.getByAltText("")).toHaveAttribute("src", "data:image/png;base64,AAA"));
  });

  test("still opens the modal with a null screenshot when capture fails (non-fatal)", async () => {
    vi.mocked(toPng).mockRejectedValueOnce(new Error("capture failed"));

    render(
      <MemoryRouter>
        <BugReportTrigger />
      </MemoryRouter>,
    );

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

    render(
      <MemoryRouter>
        <BugReportTrigger />
      </MemoryRouter>,
    );

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

    render(
      <MemoryRouter>
        <BugReportTrigger />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("bug-report-trigger"));
    expect(screen.getByTestId("bug-report-trigger")).toBeDisabled();

    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });

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

    render(
      <MemoryRouter>
        <BugReportTrigger />
      </MemoryRouter>,
    );

    await act(async () => { fireEvent.mouseDown(screen.getByTestId("bug-report-trigger")); });

    // Our own mousedown handler (bound directly on the button) must run
    // before the event bubbles up to trigger document-level listeners.
    expect(toPng).toHaveBeenCalled();
    expect(outsideClickHandler).toHaveBeenCalled();

    document.removeEventListener("mousedown", outsideClickHandler);
  });

  test("captures relative to the current scroll position, not the top of the document", async () => {
    Object.defineProperty(window, "scrollX", { value: 40, configurable: true });
    Object.defineProperty(window, "scrollY", { value: 300, configurable: true });

    render(
      <MemoryRouter>
        <BugReportTrigger />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    await waitFor(() => expect(toPng).toHaveBeenCalled());
    expect(toPng).toHaveBeenCalledWith(
      document.body,
      expect.objectContaining({
        style: expect.objectContaining({ transform: "translate(-40px, -300px)" }),
      }),
    );

    Object.defineProperty(window, "scrollX", { value: 0, configurable: true });
    Object.defineProperty(window, "scrollY", { value: 0, configurable: true });
  });
});
