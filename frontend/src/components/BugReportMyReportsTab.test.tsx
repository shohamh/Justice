import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import "../i18n";
import BugReportMyReportsTab from "./BugReportMyReportsTab";
import * as bugReportsApi from "../api/bugReports";
import type { BugReportSummary } from "../api/bugReports";

vi.mock("../api/bugReports", async () => {
  const actual = await vi.importActual<typeof import("../api/bugReports")>("../api/bugReports");
  return {
    ...actual,
    getMyBugReports: vi.fn(),
    listComments: vi.fn(),
    markBugReportSeen: vi.fn().mockResolvedValue(undefined),
  };
});

const REPORT: BugReportSummary = {
  id: "r1",
  reporter_id: "s1",
  description: "the calendar is blank",
  severity: "high",
  status: "open",
  route: "/calendar",
  nav_history: [{ path: "/super-secret-nav-path", timestamp: "2026-07-25T10:00:00Z" }],
  audit_snapshot: [{ action: "login", entity_type: "soldier" }],
  user_snapshot: { full_name: "Internal Snapshot User", rank: "סמל" },
  has_screenshot: false,
  created_at: "2026-07-25T10:05:00Z",
  updated_at: "2026-07-25T10:05:00Z",
  comment_count: 0,
  last_comment_at: null,
  has_unseen_activity: false,
};

function renderTab(expandedId: string | null = null, onToggle = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BugReportMyReportsTab expandedId={expandedId} onToggle={onToggle} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({ items: [REPORT], total: 1 });
  vi.mocked(bugReportsApi.listComments).mockResolvedValue([]);
});

describe("BugReportMyReportsTab", () => {
  it("renders the reporter's own bug reports", async () => {
    renderTab();
    expect(await screen.findByText("the calendar is blank")).toBeInTheDocument();
  });

  it("shows the empty state when the user has no bug reports", async () => {
    vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({ items: [], total: 0 });
    renderTab();
    expect(await screen.findByText("לא דיווחת על באגים")).toBeInTheDocument();
  });

  it("renders the comments panel and calls onToggle when a row is expanded (controlled)", async () => {
    const onToggle = vi.fn();
    renderTab(null, onToggle);
    const expand = await screen.findByTestId("my-bug-report-expand-r1");

    fireEvent.click(expand);

    expect(onToggle).toHaveBeenCalledWith("r1");
  });

  it("renders the comments panel when expandedId matches a report", async () => {
    renderTab("r1");
    expect(await screen.findByText("אין תגובות עדיין")).toBeInTheDocument();
    await waitFor(() => expect(bugReportsApi.listComments).toHaveBeenCalledWith("r1"));
  });

  it("calls onToggle(null) when an already-expanded row is clicked again", async () => {
    const onToggle = vi.fn();
    renderTab("r1", onToggle);
    const expand = await screen.findByTestId("my-bug-report-expand-r1");

    fireEvent.click(expand);

    expect(onToggle).toHaveBeenCalledWith(null);
  });

  it("marks the report seen when it is expanded", async () => {
    renderTab(null, vi.fn());
    const expand = await screen.findByTestId("my-bug-report-expand-r1");

    fireEvent.click(expand);

    await waitFor(() => expect(bugReportsApi.markBugReportSeen).toHaveBeenCalledWith("r1"));
  });

  it("does not mark the report seen when collapsing it", async () => {
    renderTab("r1", vi.fn());
    const expand = await screen.findByTestId("my-bug-report-expand-r1");

    fireEvent.click(expand);

    expect(bugReportsApi.markBugReportSeen).not.toHaveBeenCalled();
  });

  it("shows an unseen indicator for a report with unseen activity", async () => {
    vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({
      items: [{ ...REPORT, has_unseen_activity: true }],
      total: 1,
    });
    renderTab();

    expect(await screen.findByTestId("my-bug-report-unseen-r1")).toBeInTheDocument();
  });

  it("does not expose internal snapshots or navigation history even when a row is expanded", async () => {
    renderTab("r1");
    await screen.findByText("אין תגובות עדיין");

    expect(screen.queryByText("/super-secret-nav-path")).not.toBeInTheDocument();
    expect(screen.queryByText("Internal Snapshot User")).not.toBeInTheDocument();
    expect(screen.queryByText("login")).not.toBeInTheDocument();
  });

  it("never shows admin-only controls or import actions", async () => {
    renderTab();
    await screen.findByText("the calendar is blank");

    expect(screen.queryByTestId("bug-report-import-input")).not.toBeInTheDocument();
    expect(screen.queryByTestId(/^bug-report-status-/)).not.toBeInTheDocument();
    expect(screen.queryByTestId(/^bug-report-view-json-/)).not.toBeInTheDocument();
  });
});
