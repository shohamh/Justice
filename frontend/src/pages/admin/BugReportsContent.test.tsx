import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import "../../i18n";
import { BugReportsContent } from "./BugReportsContent";
import * as bugReportsApi from "../../api/bugReports";
import type { BugReportSummary } from "../../api/bugReports";

vi.mock("../../api/bugReports", async () => {
  const actual = await vi.importActual<typeof import("../../api/bugReports")>("../../api/bugReports");
  return {
    ...actual,
    listBugReports: vi.fn(),
    downloadBugReportExport: vi.fn(),
    updateBugReportStatus: vi.fn(),
    getBugReportJson: vi.fn(),
    fetchBugReportScreenshot: vi.fn(),
    importBugReports: vi.fn(),
    listComments: vi.fn(),
  };
});

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </MemoryRouter>,
  );
}

const SAMPLE_REPORT: BugReportSummary = {
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
  comment_count: 2,
  last_comment_at: "2026-07-25T10:07:00Z",
  has_unseen_activity: false,
};

describe("BugReportsContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({ items: [SAMPLE_REPORT], total: 1 });
    vi.mocked(bugReportsApi.downloadBugReportExport).mockResolvedValue({
      blob: new Blob(["zip"]),
      filename: "bug-reports-2026-08-14-1015.zip",
    });
    vi.mocked(bugReportsApi.listComments).mockResolvedValue([]);
  });

  it("renders the report list", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByText("the calendar is blank")).toBeInTheDocument());
    expect(screen.getByText("Test Soldier")).toBeInTheDocument();
  });

  it("updates status via the icon buttons", async () => {
    vi.mocked(bugReportsApi.updateBugReportStatus).mockResolvedValue({ ...SAMPLE_REPORT, status: "resolved" });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-status-resolved-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("bug-report-status-resolved-r1"));

    await waitFor(() => expect(bugReportsApi.updateBugReportStatus).toHaveBeenCalledWith("r1", "resolved"));
  });

  it("renders a labelled status control for each status, highlighting the current status", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-status-open-r1")).toBeInTheDocument());

    expect(screen.getByTestId("bug-report-status-open-r1")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-status-in_progress-r1")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-status-resolved-r1")).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-status-wont_fix-r1")).toBeInTheDocument();

    // SAMPLE_REPORT.status is "open" — only that button should be marked pressed/active.
    expect(screen.getByTestId("bug-report-status-open-r1")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("bug-report-status-in_progress-r1")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("bug-report-status-resolved-r1")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("bug-report-status-wont_fix-r1")).toHaveAttribute("aria-pressed", "false");

    expect(screen.getByTestId("bug-report-status-open-r1").parentElement).toHaveTextContent("פתוח");
    expect(screen.getByTestId("bug-report-status-in_progress-r1").parentElement).toHaveTextContent("בטיפול");
    expect(screen.getByTestId("bug-report-status-resolved-r1").parentElement).toHaveTextContent("טופל");
    expect(screen.getByTestId("bug-report-status-wont_fix-r1").parentElement).toHaveTextContent("לא יטופל");
  });

  it("colors the row background according to the report's status", async () => {
    const inProgressReport = { ...SAMPLE_REPORT, id: "r2", status: "in_progress" as const };
    const resolvedReport = { ...SAMPLE_REPORT, id: "r3", status: "resolved" as const };
    const wontFixReport = { ...SAMPLE_REPORT, id: "r4", status: "wont_fix" as const };
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({
      items: [SAMPLE_REPORT, inProgressReport, resolvedReport, wontFixReport],
      total: 4,
    });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-row-r1")).toBeInTheDocument());

    const openRow = screen.getByTestId("bug-report-row-r1");
    const inProgressRow = screen.getByTestId("bug-report-row-r2");
    const resolvedRow = screen.getByTestId("bug-report-row-r3");
    const wontFixRow = screen.getByTestId("bug-report-row-r4");

    expect(openRow).toHaveClass("bg-red-100");
    expect(inProgressRow).toHaveClass("bg-amber-100");
    expect(resolvedRow).toHaveClass("bg-emerald-100");
    expect(wontFixRow).toHaveClass("bg-slate-200");
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
    await waitFor(() => expect(screen.getByTestId("bug-report-status-resolved-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("bug-report-status-resolved-r1"));

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

    fireEvent.click(screen.getByRole("button", { name: "הרחב" }));

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

    fireEvent.click(screen.getByRole("button", { name: "הרחב" }));
    await waitFor(() => expect(createObjectURLSpy).toHaveBeenCalled());

    cleanup();

    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:fake-url");

    createObjectURLSpy.mockRestore();
    revokeObjectURLSpy.mockRestore();
  });

  it("opens the screenshot in a fullscreen preview modal when clicked", async () => {
    const reportWithScreenshot = { ...SAMPLE_REPORT, has_screenshot: true };
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({ items: [reportWithScreenshot], total: 1 });
    vi.mocked(bugReportsApi.fetchBugReportScreenshot).mockResolvedValue(new Blob(["fake"]));

    if (!URL.createObjectURL) URL.createObjectURL = vi.fn();
    const createObjectURLSpy = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:fake-url");

    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-row-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "הרחב" }));
    await waitFor(() => expect(createObjectURLSpy).toHaveBeenCalled());

    const screenshot = await screen.findByAltText("screenshot");
    fireEvent.click(screenshot);

    expect(await screen.findByText("הורדה")).toBeInTheDocument();
    expect(screen.getByText("✕")).toBeInTheDocument();

    createObjectURLSpy.mockRestore();
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

  it("downloads all active bug reports by default using a temporary object URL", async () => {
    const createObjectURLSpy = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:bug-report-export");
    const revokeObjectURLSpy = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const appendChildSpy = vi.spyOn(document.body, "appendChild");
    const removeChildSpy = vi.spyOn(document.body, "removeChild");

    renderWithProviders(<BugReportsContent />);
    const exportButton = await screen.findByRole("button", { name: "ייצוא לMarkdown לטובת טיפול אייג'נטי" });

    fireEvent.click(exportButton);

    await waitFor(() =>
      expect(bugReportsApi.downloadBugReportExport).toHaveBeenCalledWith({ scope: "all_active" }),
    );
    await waitFor(() => expect(createObjectURLSpy).toHaveBeenCalled());

    const anchor = appendChildSpy.mock.calls.at(-1)?.[0] as HTMLAnchorElement | undefined;
    expect(anchor).toBeDefined();
    expect(anchor?.getAttribute("href")).toBe("blob:bug-report-export");
    expect(anchor?.getAttribute("download")).toBe("bug-reports-2026-08-14-1015.zip");
    expect(removeChildSpy).toHaveBeenCalledWith(anchor);
    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:bug-report-export");

    createObjectURLSpy.mockRestore();
    revokeObjectURLSpy.mockRestore();
    appendChildSpy.mockRestore();
    removeChildSpy.mockRestore();
  });

  it("downloads the filtered export with the current active filters only", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-filter-severity")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("bug-report-filter-severity"), { target: { value: "high" } });
    fireEvent.change(screen.getByTestId("bug-report-filter-status"), { target: { value: "open" } });
    fireEvent.change(screen.getByTestId("bug-report-export-scope"), { target: { value: "filtered" } });
    fireEvent.click(screen.getByRole("button", { name: "ייצוא לMarkdown לטובת טיפול אייג'נטי" }));

    await waitFor(() =>
      expect(bugReportsApi.downloadBugReportExport).toHaveBeenCalledWith({
        scope: "filtered",
        severity: "high",
        status: "open",
      }),
    );
  });

  it("omits inactive status filters from the filtered export request", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-filter-status")).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("bug-report-filter-status"), { target: { value: "resolved" } });
    fireEvent.change(screen.getByTestId("bug-report-export-scope"), { target: { value: "filtered" } });
    fireEvent.click(screen.getByRole("button", { name: "ייצוא לMarkdown לטובת טיפול אייג'נטי" }));

    await waitFor(() =>
      expect(bugReportsApi.downloadBugReportExport).toHaveBeenCalledWith({
        scope: "filtered",
        severity: undefined,
        status: undefined,
      }),
    );
  });

  it("keeps export selection independent from pagination", async () => {
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({ items: [SAMPLE_REPORT], total: 21 });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByRole("button", { name: "2" })).toBeInTheDocument());

    fireEvent.change(screen.getByTestId("bug-report-filter-severity"), { target: { value: "medium" } });
    fireEvent.change(screen.getByTestId("bug-report-filter-status"), { target: { value: "in_progress" } });
    fireEvent.change(screen.getByTestId("bug-report-export-scope"), { target: { value: "filtered" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "2" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "2" }));
    await waitFor(() =>
      expect(bugReportsApi.listBugReports).toHaveBeenLastCalledWith(
        expect.objectContaining({ severity: "medium", status: "in_progress", offset: 20, limit: 20 }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "ייצוא לMarkdown לטובת טיפול אייג'נטי" }));

    await waitFor(() =>
      expect(bugReportsApi.downloadBugReportExport).toHaveBeenCalledWith({
        scope: "filtered",
        severity: "medium",
        status: "in_progress",
      }),
    );
  });

  it("disables the export controls while the download is in progress", async () => {
    vi.mocked(bugReportsApi.downloadBugReportExport).mockImplementation(
      () => new Promise(() => {}),
    );
    renderWithProviders(<BugReportsContent />);
    const exportButton = await screen.findByRole("button", { name: "ייצוא לMarkdown לטובת טיפול אייג'נטי" });
    const exportScope = screen.getByTestId("bug-report-export-scope");

    fireEvent.click(exportButton);

    await waitFor(() => expect(exportButton).toBeDisabled());
    expect(exportScope).toBeDisabled();
  });

  it("shows a translated inline error when the export download fails", async () => {
    vi.mocked(bugReportsApi.downloadBugReportExport).mockRejectedValue(new Error("network error"));
    renderWithProviders(<BugReportsContent />);
    const exportButton = await screen.findByRole("button", { name: "ייצוא לMarkdown לטובת טיפול אייג'נטי" });

    fireEvent.click(exportButton);

    await waitFor(() => expect(screen.getByTestId("bug-report-export-error")).toBeInTheDocument());
    expect(screen.getByTestId("bug-report-export-error")).toHaveTextContent("שגיאה בייצוא הדיווחים");
  });

  it("expands the row via the dedicated expand toggle button", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-row-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "הרחב" }));

    expect(screen.getByText("/calendar")).toBeInTheDocument();
  });

  it("expands the row by clicking anywhere on it, not just the toggle button", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-row-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("bug-report-row-r1"));

    expect(screen.getByText("/calendar")).toBeInTheDocument();
  });

  it("clicking a status icon button does not also expand the row", async () => {
    vi.mocked(bugReportsApi.updateBugReportStatus).mockResolvedValue({ ...SAMPLE_REPORT, status: "resolved" });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-status-resolved-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("bug-report-status-resolved-r1"));

    await waitFor(() => expect(bugReportsApi.updateBugReportStatus).toHaveBeenCalledWith("r1", "resolved"));
    expect(screen.queryByText("/calendar")).not.toBeInTheDocument();
  });

  it("renders the comments panel inline at the bottom of expanded content without a modal trigger", async () => {
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByTestId("bug-report-row-r1")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "הרחב" }));

    expect(await screen.findByText("אין תגובות עדיין")).toBeInTheDocument();
    expect(screen.queryByTestId("bug-report-comments-r1")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders comment activity columns and an em dash when there is no last response", async () => {
    const noResponseReport = {
      ...SAMPLE_REPORT,
      id: "r-no-response",
      description: "no response report",
      comment_count: 0,
      last_comment_at: null,
    };
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({
      items: [SAMPLE_REPORT, noResponseReport],
      total: 2,
    });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByText("no response report")).toBeInTheDocument());

    expect(screen.getByRole("columnheader", { name: "תגובות" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "תגובה אחרונה" })).toBeInTheDocument();
    expect(screen.getByText("2", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByTestId("bug-report-row-r-no-response")).toHaveTextContent("—");
    expect(screen.getByText(new Date(SAMPLE_REPORT.last_comment_at!).toLocaleString("he-IL"))).toBeInTheDocument();
  });

  it("sorts latest responses chronologically from their raw ISO timestamps and keeps null values explicit", async () => {
    const olderResponse = {
      ...SAMPLE_REPORT,
      id: "r-older-response",
      description: "older response",
      last_comment_at: "2026-07-20T10:07:00Z",
    };
    const noResponse = {
      ...SAMPLE_REPORT,
      id: "r-no-response",
      description: "no response",
      last_comment_at: null,
    };
    const latestResponse = {
      ...SAMPLE_REPORT,
      id: "r-latest-response",
      description: "latest response",
      last_comment_at: "2026-07-28T10:07:00Z",
    };
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({
      items: [latestResponse, noResponse, olderResponse],
      total: 3,
    });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByText("latest response")).toBeInTheDocument());

    const descriptionsInOrder = () =>
      screen.getAllByTestId(/^bug-report-row-/).map((row) => row.textContent ?? "");

    fireEvent.click(screen.getByRole("columnheader", { name: "תגובה אחרונה" }));

    await waitFor(() => {
      const rows = descriptionsInOrder();
      expect(rows[0]).toContain("older response");
      expect(rows[1]).toContain("latest response");
      expect(rows[2]).toContain("no response");
    });
  });

  it("sorts rows by date when the date column header is clicked", async () => {
    const olderReport = {
      ...SAMPLE_REPORT,
      id: "r-older",
      description: "older report",
      created_at: "2026-07-20T10:05:00Z",
    };
    const newerReport = {
      ...SAMPLE_REPORT,
      id: "r-newer",
      description: "newer report",
      created_at: "2026-07-28T10:05:00Z",
    };
    vi.mocked(bugReportsApi.listBugReports).mockResolvedValue({
      items: [olderReport, newerReport],
      total: 2,
    });
    renderWithProviders(<BugReportsContent />);
    await waitFor(() => expect(screen.getByText("older report")).toBeInTheDocument());

    const getDescriptionOrder = () =>
      screen.getAllByTestId(/^bug-report-row-/).map((row) => row.textContent);

    // Initial (unsorted/server) order: older, then newer.
    expect(getDescriptionOrder()[0]).toContain("older report");

    fireEvent.click(screen.getByText("תאריך"));
    await waitFor(() => expect(getDescriptionOrder()[0]).toContain("older report"));

    fireEvent.click(screen.getByText("תאריך"));
    await waitFor(() => expect(getDescriptionOrder()[0]).toContain("newer report"));
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
