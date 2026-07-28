import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BugReportsContent } from "./BugReportsContent";
import * as bugReportsApi from "../../api/bugReports";

vi.mock("../../api/bugReports", async () => {
  const actual = await vi.importActual<typeof import("../../api/bugReports")>("../../api/bugReports");
  return {
    ...actual,
    listBugReports: vi.fn(),
    updateBugReportStatus: vi.fn(),
    getBugReportJson: vi.fn(),
    fetchBugReportScreenshot: vi.fn(),
    importBugReports: vi.fn(),
  };
});

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const SAMPLE_REPORT = {
  id: "r1",
  reporter_id: "s1",
  description: "the calendar is blank",
  severity: "high" as const,
  status: "open" as const,
  route: "/calendar",
  nav_history: [{ path: "/", timestamp: "2026-07-25T10:00:00Z" }],
  audit_snapshot: [{ action: "login", entity_type: "soldier" }],
  user_snapshot: { full_name: "Test Soldier" },
  has_screenshot: false,
  created_at: "2026-07-25T10:05:00Z",
  updated_at: "2026-07-25T10:05:00Z",
};

describe("BugReportsContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({ items: [SAMPLE_REPORT], total: 1 });
  });

  it("renders the report list", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByText("the calendar is blank")).toBeInTheDocument());
    expect(screen.getByText("Test Soldier")).toBeInTheDocument();
  });

  it("updates status via the dropdown", async () => {
    vi.mocked(bugReportsApi.updateBugReportStatus).mockResolvedValue({ ...SAMPLE_REPORT, status: "resolved" });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-status-r1")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("bug-report-status-r1"), { target: { value: "resolved" } });

    await waitFor(() => expect(bugReportsApi.updateBugReportStatus).toHaveBeenCalledWith("r1", "resolved"));
  });

  it("filters by severity", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-filter-severity")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("bug-report-filter-severity"), { target: { value: "high" } });

    await waitFor(() => expect(bugReportsApi.listBugReports).toHaveBeenLastCalledWith(
      expect.objectContaining({ severity: "high" }),
    ));
  });

  it("shows an inline error and does not crash when the status update fails", async () => {
    vi.mocked(bugReportsApi.updateBugReportStatus).mockRejectedValue(new Error("network error"));
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-status-r1")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("bug-report-status-r1"), { target: { value: "resolved" } });

    await waitFor(() => expect(screen.getByTestId("bug-report-status-error-r1")).toBeInTheDocument());
  });

  it("shows a loading state while the report list is fetching", async () => {
    vi.mocked(bugReportsApi.listBugReports).mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<BugReportsContent />);
    expect(screen.getByTestId("bug-reports-loading")).toBeInTheDocument();
  });

  it("shows an error state when the report list fails to load", async () => {
    vi.mocked(bugReportsApi.listBugReports).mockRejectedValue(new Error("network error"));
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-reports-error")).toBeInTheDocument());
  });

  it("shows the route and user snapshot fields when a row is expanded", async () => {
    const fullReport = {
      ...SAMPLE_REPORT,
      user_snapshot: { full_name: "Test Soldier", rank: "סמל", role: "soldier", personal_number: "12345" },
    };
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({ items: [fullReport], total: 1 });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-row-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("bug-report-row-r1"));

    expect(screen.getByText("/calendar")).toBeInTheDocument();
    expect(screen.getByText(/סמל/)).toBeInTheDocument();
    expect(screen.getByText(/12345/)).toBeInTheDocument();
  });

  it("revokes screenshot blob URLs on unmount", async () => {
    const reportWithScreenshot = { ...SAMPLE_REPORT, has_screenshot: true };
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({ items: [reportWithScreenshot], total: 1 });
    vi.mocked(bugReportsApi.fetchBugReportScreenshot).mockResolvedValue(new Blob(["fake"]));

    if (!URL.createObjectURL) URL.createObjectURL = vi.fn();
    if (!URL.revokeObjectURL) URL.revokeObjectURL = vi.fn();
    const createObjectURLSpy = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:fake-url");
    const revokeObjectURLSpy = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-row-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("bug-report-row-r1"));
    await waitFor(() => expect(createObjectURLSpy).toHaveBeenCalled());

    cleanup();

    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:fake-url");

    createObjectURLSpy.mockRestore();
    revokeObjectURLSpy.mockRestore();
  });

  it("imports a batch of JSON files and shows a summary, then refreshes the list", async () => {
    vi.mocked(bugReportsApi.importBugReports).mockResolvedValue({
      results: [
        { filename: "a.json", status: "imported", detail: null },
        { filename: "b.json", status: "already_exists", detail: "already_exists" },
      ],
    });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-import-input")).toBeInTheDocument());

    const fileA = new File(["{}"], "a.json", { type: "application/json" });
    const fileB = new File(["{}"], "b.json", { type: "application/json" });
    fireEvent.change(screen.getByTestId("bug-report-import-input"), { target: { files: [fileA, fileB] } });

    await waitFor(() => expect(bugReportsApi.importBugReports).toHaveBeenCalledWith([fileA, fileB]));
    await waitFor(() => expect(screen.getByTestId("bug-report-import-summary")).toHaveTextContent("יובאו 1 מתוך 2"));
    expect(bugReportsApi.listBugReports).toHaveBeenCalledTimes(2);
  });

  it("shows an inline error when the import request itself fails", async () => {
    vi.mocked(bugReportsApi.importBugReports).mockRejectedValue(new Error("network error"));
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-import-input")).toBeInTheDocument());

    const file = new File(["{}"], "a.json", { type: "application/json" });
    fireEvent.change(screen.getByTestId("bug-report-import-input"), { target: { files: [file] } });

    await waitFor(() => expect(screen.getByTestId("bug-report-import-error")).toBeInTheDocument());
  });
});
