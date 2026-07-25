import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import BugReportTrigger from "./BugReportTrigger";

vi.mock("html-to-image", () => ({ toPng: vi.fn().mockResolvedValue("data:image/png;base64,AAA") }));
vi.mock("../hooks/useNavigationHistory", () => ({ useNavigationHistory: () => [] }));

describe("BugReportTrigger", () => {
  test("opens the bug report modal on click, portaled to document.body", async () => {
    render(
      <MemoryRouter>
        <BugReportTrigger />
      </MemoryRouter>,
    );

    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).toBeNull();

    fireEvent.click(screen.getByTestId("bug-report-trigger"));

    expect(document.body.querySelector('[data-testid="bug-report-modal-overlay"]')).not.toBeNull();

    // Let the mocked toPng() promise resolve inside act() before the test ends,
    // so the modal's screenshot-capture effect doesn't leave a dangling state update.
    await waitFor(() => expect(screen.queryByText("מצלם צילום מסך...")).not.toBeInTheDocument());
  });
});
