import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import "../i18n";
import NotificationsPage from "./NotificationsPage";
import { BugReportModalProvider } from "../contexts/BugReportModalContext";
import { listNotifications } from "../api/notifications";
import * as bugReportsApi from "../api/bugReports";

const navigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("../hooks/useNavigationHistory", () => ({ useNavigationHistory: () => [] }));

vi.mock("../api/notifications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/notifications")>()),
  listNotifications: vi.fn(),
}));

vi.mock("../api/bugReports", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/bugReports")>()),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
  getMyBugReports: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  listComments: vi.fn().mockResolvedValue([]),
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <BugReportModalProvider>
          <NotificationsPage />
        </BugReportModalProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    navigate.mockReset();
    vi.mocked(listNotifications).mockResolvedValue({
      items: [{
        id: "notification-1",
        soldier_id: "soldier-1",
        title: "תגובה חדשה לדיווח באג",
        body: null,
        type: "bug_report_comment",
        reference_type: "bug_report",
        reference_id: "report-123",
        is_read: false,
        created_at: "2026-08-03T12:00:00Z",
      }],
      total: 1,
    });
  });

  it("opens the referenced bug report in the feedback modal instead of navigating", async () => {
    vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({
      items: [{
        id: "report-123", reporter_id: "s1", description: "opened from notifications page", severity: "low", status: "open",
        route: "/", nav_history: null, audit_snapshot: null, user_snapshot: null, has_screenshot: false,
        created_at: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:00:00Z",
        comment_count: 0, last_comment_at: null, has_unseen_activity: true,
      }],
      total: 1,
    });
    vi.mocked(bugReportsApi.listComments).mockResolvedValue([]);

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "תגובה חדשה לדיווח באג" }));

    expect(await screen.findByText("opened from notifications page")).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });
});
