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
        <BugReportModal screenshot="data:image/png;base64,AAA" onClose={vi.fn()} />
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
        <BugReportModal screenshot="data:image/png;base64,AAA" onClose={vi.fn()} />
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
        <BugReportModal screenshot="data:image/png;base64,AAA" onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("bug-report-submit")).toBeDisabled();
  });

  test("submits via Ctrl+Enter in the description textarea", async () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal screenshot="data:image/png;base64,AAA" onClose={vi.fn()} />
      </MemoryRouter>,
    );

    const textarea = screen.getByTestId("bug-report-description");
    fireEvent.change(textarea, { target: { value: "ctrl enter works" } });
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ description: "ctrl enter works" }),
    ));
  });

  test("does not submit via Ctrl+Enter when the description is empty", () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal screenshot="data:image/png;base64,AAA" onClose={vi.fn()} />
      </MemoryRouter>,
    );

    fireEvent.keyDown(screen.getByTestId("bug-report-description"), { key: "Enter", ctrlKey: true });
    expect(submitBugReport).not.toHaveBeenCalled();
  });

  test("keeps the dialog scrollable and actions reachable on small viewports, and still submits a long description", async () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal screenshot="data:image/png;base64,AAA" onClose={vi.fn()} />
      </MemoryRouter>,
    );

    const overlay = screen.getByTestId("bug-report-modal-overlay");
    expect(overlay.className).toMatch(/overflow-y-auto/);

    const dialog = screen.getByTestId("bug-report-modal-dialog");
    expect(dialog.className).toMatch(/flex/);
    expect(dialog.className).toMatch(/flex-col/);
    expect(dialog.className).toMatch(/max-h-\[calc\(100dvh-2rem\)\]/);

    const content = screen.getByTestId("bug-report-modal-content");
    expect(content.className).toMatch(/min-h-0/);
    expect(content.className).toMatch(/overflow-y-auto/);

    const actions = screen.getByTestId("bug-report-modal-actions");
    expect(actions).toBeInTheDocument();
    expect(actions.className).toMatch(/shrink-0/);

    const longDescription = "תיאור ארוך מאוד ".repeat(50);
    fireEvent.change(screen.getByTestId("bug-report-description"), { target: { value: longDescription } });
    fireEvent.click(screen.getByTestId("bug-report-submit"));

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ description: longDescription.trim() }),
    ));
  });

  test("shows a fallback message and still allows submission when screenshot capture failed", async () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal screenshot={null} onClose={vi.fn()} />
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
