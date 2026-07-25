import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import BugReportModal from "./BugReportModal";
import { submitBugReport } from "../api/bugReports";

vi.mock("html-to-image", () => ({
  toPng: vi.fn().mockResolvedValue("data:image/png;base64,AAA"),
}));
vi.mock("../api/bugReports", () => ({
  submitBugReport: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("../hooks/useNavigationHistory", () => ({
  useNavigationHistory: () => [{ path: "/", timestamp: "2026-07-25T10:00:00Z" }],
}));

describe("BugReportModal", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  test("submits the selected severity, description, and route", async () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal onClose={vi.fn()} />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByTestId("bug-report-description"), { target: { value: "the button breaks" } });
    fireEvent.click(screen.getByTestId("bug-report-severity-high"));
    fireEvent.click(screen.getByTestId("bug-report-submit"));

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "high", description: "the button breaks", route: "/duty" }),
    ));
  });

  test("defaults to medium severity when none is explicitly chosen", async () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal onClose={vi.fn()} />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByTestId("bug-report-description"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("bug-report-submit"));

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "medium" }),
    ));
  });

  test("disables submit until a description is entered", async () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("bug-report-submit")).toBeDisabled();

    // Let the mocked toPng() promise resolve inside act() before the test ends,
    // so the effect's setScreenshot/setCapturing updates aren't left dangling.
    await waitFor(() => expect(screen.queryByText("מצלם צילום מסך...")).not.toBeInTheDocument());
  });
});
