import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
});
