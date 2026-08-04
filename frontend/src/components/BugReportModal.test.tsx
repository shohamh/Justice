import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type React from "react";
import "../i18n";
import BugReportModal from "./BugReportModal";
import { submitBugReport } from "../api/bugReports";

vi.mock("../api/bugReports", () => ({
  submitBugReport: vi.fn().mockResolvedValue(undefined),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
  getMyBugReports: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  listComments: vi.fn().mockResolvedValue([]),
  createComment: vi.fn(),
  uploadCommentAttachment: vi.fn(),
  bugReportCommentAttachmentDownloadUrl: vi.fn(() => ""),
  markBugReportSeen: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("../hooks/useNavigationHistory", () => ({
  useNavigationHistory: () => [{ path: "/", timestamp: "2026-07-25T10:00:00Z" }],
}));

function renderModal(props: Partial<React.ComponentProps<typeof BugReportModal>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/duty"]}>
        <BugReportModal screenshot={null} onClose={vi.fn()} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BugReportModal", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  test("submits the selected severity, description, and route", async () => {
    renderModal({ screenshot: "data:image/png;base64,AAA" });

    fireEvent.change(screen.getByTestId("bug-report-description"), { target: { value: "the button breaks" } });
    fireEvent.click(screen.getByTestId("bug-report-severity-high"));
    fireEvent.click(screen.getByTestId("bug-report-submit"));

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "high", description: "the button breaks", route: "/duty" }),
    ));
  });

  test("defaults to medium severity when none is explicitly chosen", async () => {
    renderModal({ screenshot: "data:image/png;base64,AAA" });

    fireEvent.change(screen.getByTestId("bug-report-description"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("bug-report-submit"));

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "medium" }),
    ));
  });

  test("disables submit until a description is entered", async () => {
    renderModal({ screenshot: "data:image/png;base64,AAA" });
    expect(screen.getByTestId("bug-report-submit")).toBeDisabled();
  });

  test("submits via Ctrl+Enter in the description textarea", async () => {
    renderModal({ screenshot: "data:image/png;base64,AAA" });

    const textarea = screen.getByTestId("bug-report-description");
    fireEvent.change(textarea, { target: { value: "ctrl enter works" } });
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ description: "ctrl enter works" }),
    ));
  });

  test("does not submit via Ctrl+Enter when the description is empty", () => {
    renderModal({ screenshot: "data:image/png;base64,AAA" });

    fireEvent.keyDown(screen.getByTestId("bug-report-description"), { key: "Enter", ctrlKey: true });
    expect(submitBugReport).not.toHaveBeenCalled();
  });

  test("keeps the dialog scrollable and actions reachable on small viewports, and still submits a long description", async () => {
    renderModal({ screenshot: "data:image/png;base64,AAA" });

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
    renderModal();

    expect(screen.getByText("לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("bug-report-description"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("bug-report-submit"));

    await waitFor(() => expect(submitBugReport).toHaveBeenCalledWith(
      expect.objectContaining({ screenshot: null }),
    ));
  });

  test("defaults to the new-report tab", async () => {
    renderModal();
    expect(screen.getByTestId("bug-report-tab-new")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("bug-report-description")).toBeInTheDocument();
  });

  test("switches to the my-reports tab and shows the reporter's own reports", async () => {
    const { getMyBugReports } = await import("../api/bugReports");
    vi.mocked(getMyBugReports).mockResolvedValue({
      items: [{
        id: "r1", reporter_id: "s1", description: "my old report", severity: "low", status: "open",
        route: "/", nav_history: null, audit_snapshot: null, user_snapshot: null, has_screenshot: false,
        created_at: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:00:00Z",
        comment_count: 0, last_comment_at: null, has_unseen_activity: false,
      }],
      total: 1,
    });

    renderModal();

    fireEvent.click(screen.getByTestId("bug-report-tab-mine"));

    expect(await screen.findByText("my old report")).toBeInTheDocument();
    expect(screen.queryByTestId("bug-report-description")).not.toBeInTheDocument();
  });

  test("opens directly on the my-reports tab with a report expanded when given initialTab/initialReportId", async () => {
    const { getMyBugReports, listComments, markBugReportSeen } = await import("../api/bugReports");
    vi.mocked(getMyBugReports).mockResolvedValue({
      items: [{
        id: "r1", reporter_id: "s1", description: "deep-linked report", severity: "low", status: "open",
        route: "/", nav_history: null, audit_snapshot: null, user_snapshot: null, has_screenshot: false,
        created_at: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:00:00Z",
        comment_count: 0, last_comment_at: null, has_unseen_activity: true,
      }],
      total: 1,
    });
    vi.mocked(listComments).mockResolvedValue([]);

    renderModal({ initialTab: "mine", initialReportId: "r1" });

    expect(screen.getByTestId("bug-report-tab-mine")).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("אין תגובות עדיין")).toBeInTheDocument();
    await waitFor(() => expect(listComments).toHaveBeenCalledWith("r1"));
    await waitFor(() => expect(markBugReportSeen).toHaveBeenCalledWith("r1"));
  });

  test("shows an unseen-count badge on the my-reports tab", async () => {
    const { getMyBugReportsUnseenCount } = await import("../api/bugReports");
    vi.mocked(getMyBugReportsUnseenCount).mockResolvedValue({ count: 2 });

    renderModal();

    expect(await screen.findByTestId("bug-report-tab-mine-badge")).toHaveTextContent("2");
  });
});
