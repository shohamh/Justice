import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import "../i18n";
import MyBugReportsPage from "./MyBugReportsPage";
import * as bugReportsApi from "../api/bugReports";
import type { BugReportSummary } from "../api/bugReports";

vi.mock("../api/bugReports", async () => {
  const actual = await vi.importActual<typeof import("../api/bugReports")>("../api/bugReports");
  return {
    ...actual,
    getMyBugReports: vi.fn(),
    listComments: vi.fn(),
  };
});

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

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
};

function renderPage(initialEntries = ["/my-bug-reports"]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <QueryClientProvider client={queryClient}>
        <MyBugReportsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({ items: [REPORT], total: 1 });
  vi.mocked(bugReportsApi.listComments).mockResolvedValue([]);
});

describe("MyBugReportsPage", () => {
  it("renders the reporter's own bug reports", async () => {
    renderPage();

    expect(await screen.findByText("the calendar is blank")).toBeInTheDocument();
  });

  it("shows the empty state when the user has no bug reports", async () => {
    vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({ items: [], total: 0 });
    renderPage();

    expect(await screen.findByText("לא דיווחת על באגים")).toBeInTheDocument();
  });

  it("expanding a row mounts the inline reply panel for that report and shows no admin controls", async () => {
    renderPage();
    const expand = await screen.findByTestId("my-bug-report-expand-r1");

    fireEvent.click(expand);

    expect(await screen.findByText("אין תגובות עדיין")).toBeInTheDocument();
    await waitFor(() => expect(bugReportsApi.listComments).toHaveBeenCalledWith("r1"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("never shows admin-only controls or import actions", async () => {
    renderPage();
    await screen.findByText("the calendar is blank");

    expect(screen.queryByTestId("bug-report-import-input")).not.toBeInTheDocument();
    expect(screen.queryByTestId(/^bug-report-status-/)).not.toBeInTheDocument();
    expect(screen.queryByTestId(/^bug-report-view-json-/)).not.toBeInTheDocument();
  });

  it("does not expose internal snapshots or navigation history even when a row is expanded", async () => {
    renderPage();
    const expand = await screen.findByTestId("my-bug-report-expand-r1");

    fireEvent.click(expand);
    await screen.findByText("אין תגובות עדיין");

    expect(screen.queryByText("/super-secret-nav-path")).not.toBeInTheDocument();
    expect(screen.queryByText("Internal Snapshot User")).not.toBeInTheDocument();
    expect(screen.queryByText("login")).not.toBeInTheDocument();
  });

  it("auto-expands the report referenced by the report query parameter", async () => {
    renderPage(["/my-bug-reports?report=r1"]);

    expect(await screen.findByText("אין תגובות עדיין")).toBeInTheDocument();
    await waitFor(() => expect(bugReportsApi.listComments).toHaveBeenCalledWith("r1"));
  });

  it("does not auto-expand anything when the report parameter references an id not in the list", async () => {
    renderPage(["/my-bug-reports?report=missing"]);
    await screen.findByText("the calendar is blank");

    expect(screen.queryByText("אין תגובות עדיין")).not.toBeInTheDocument();
  });
});
