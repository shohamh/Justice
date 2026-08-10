import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import "../i18n";
import NotificationsPage from "./NotificationsPage";
import { BugReportModalProvider } from "../contexts/BugReportModalContext";
import { listNotifications } from "../api/notifications";
import * as swapsApi from "../api/swaps";
import * as rangesApi from "../api/ranges";
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
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ loggedIn: true }) }));

vi.mock("../api/notifications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/notifications")>()),
  listNotifications: vi.fn(),
}));

vi.mock("../api/swaps");
vi.mock("../api/ranges");

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
        metadata: null,
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

  it("always shows mark-read and dismiss buttons regardless of type", async () => {
    vi.mocked(listNotifications).mockResolvedValue({
      items: [{
        id: "notification-1", soldier_id: "soldier-1", title: "הכרזה",
        body: null, type: "announcement", reference_type: null, reference_id: null,
        is_read: false, created_at: "2026-08-03T12:00:00Z", metadata: null,
      }],
      total: 1,
    });

    renderPage();

    await screen.findByText("הכרזה");
    expect(screen.getByLabelText("סמן כנקרא")).toBeInTheDocument();
    expect(screen.getByLabelText("מחק")).toBeInTheDocument();
    expect(screen.queryByLabelText("אשר")).not.toBeInTheDocument();
  });

  it("shows approve/reject for swap_offer_incoming and calls the soldier-decision API", async () => {
    vi.mocked(listNotifications).mockResolvedValue({
      items: [{
        id: "notification-1", soldier_id: "soldier-1", title: "הצעת החלפה",
        body: null, type: "swap_offer_incoming", reference_type: "swap_request", reference_id: "req1",
        is_read: false, created_at: "2026-08-03T12:00:00Z", metadata: null,
      }],
      total: 1,
    });
    vi.mocked(swapsApi.soldierApproveSwap).mockResolvedValue({} as never);

    renderPage();

    await screen.findByText("הצעת החלפה");
    fireEvent.click(screen.getByLabelText("אשר"));

    await waitFor(() => expect(swapsApi.soldierApproveSwap).toHaveBeenCalledWith("req1"));
  });

  it("shows approve/reject for range_excusal_pending and calls decideRangeExcusal with metadata.event_id", async () => {
    vi.mocked(listNotifications).mockResolvedValue({
      items: [{
        id: "notification-1", soldier_id: "soldier-1", title: "בקשת פטור ממטווח",
        body: null, type: "range_excusal_pending", reference_type: "range_excusal_request", reference_id: "req1",
        is_read: false, created_at: "2026-08-03T12:00:00Z", metadata: { event_id: "evt1" },
      }],
      total: 1,
    });
    vi.mocked(rangesApi.decideRangeExcusal).mockResolvedValue({} as never);

    renderPage();

    await screen.findByText("בקשת פטור ממטווח");
    fireEvent.click(screen.getByLabelText("דחה"));

    await waitFor(() => expect(rangesApi.decideRangeExcusal).toHaveBeenCalledWith("evt1", "req1", false));
  });
});
