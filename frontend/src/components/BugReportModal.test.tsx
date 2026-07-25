import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import BugReportModal from "./BugReportModal";
import { submitBugReport } from "../api/bugReports";

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
        <BugReportModal screenshot="data:image/png;base64,AAA" capturing={false} onClose={vi.fn()} />
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
        <BugReportModal screenshot="data:image/png;base64,AAA" capturing={false} onClose={vi.fn()} />
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
        <BugReportModal screenshot="data:image/png;base64,AAA" capturing={false} onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("bug-report-submit")).toBeDisabled();
  });

  test("shows a capturing indicator while capturing is true, with no screenshot preview", () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal screenshot={null} capturing={true} onClose={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.getByText("מצלם צילום מסך...")).toBeInTheDocument();
  });

  test("shows a fallback message and still allows submission when screenshot capture failed", async () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal screenshot={null} capturing={false} onClose={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.getByText("לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("bug-report-description"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("bug-report-submit"));

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ screenshot: null }),
    ));
  });
});
