import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
});
