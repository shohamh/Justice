import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import NotificationBell from "./NotificationBell";
import { BugReportModalProvider } from "../contexts/BugReportModalContext";
import * as notificationsApi from "../api/notifications";
import * as bugReportsApi from "../api/bugReports";

vi.mock("../api/notifications");
vi.mock("../hooks/useNavigationHistory", () => ({ useNavigationHistory: () => [] }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ loggedIn: true }) }));
vi.mock("../api/bugReports", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/bugReports")>()),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
  getMyBugReports: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  listComments: vi.fn().mockResolvedValue([]),
}));

function renderBell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <BugReportModalProvider>
          <NotificationBell />
        </BugReportModalProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

const baseNotification = {
  id: "n1",
  soldier_id: "s1",
  body: null,
  reference_type: null,
  reference_id: null,
  is_read: false,
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(notificationsApi.getUnreadCount).mockResolvedValue({ count: 2 });
});

describe("NotificationBell icon differentiation", () => {
  it("shows a different icon for system_announcement than for announcement", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [
        { ...baseNotification, id: "n1", title: "Scoped", type: "announcement" },
        { ...baseNotification, id: "n2", title: "Org wide", type: "system_announcement" },
      ],
      total: 2,
    });
    renderBell();
    const bellButton = await screen.findByTestId("notification-bell");
    bellButton.click();
    const scopedRow = await screen.findByText("Scoped");
    const orgWideRow = await screen.findByText("Org wide");
    expect(scopedRow.closest("div")?.parentElement?.textContent).toContain("📢");
    expect(orgWideRow.closest("div")?.parentElement?.textContent).toContain("📣");
  });
  it("shows the range lifecycle icon and label", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [{ ...baseNotification, title: "Range cancelled", type: "range_cancelled" }],
      total: 1,
    });
    renderBell();
    (await screen.findByTestId("notification-bell")).click();
    const row = await screen.findByText("Range cancelled");
    expect(row.closest("div")?.parentElement?.textContent).toContain(String.fromCodePoint(0x1f6ab));
    expect(document.querySelector("[aria-label=\"range_cancelled\"]")).toBeTruthy();
  });

  it("shows a different icon for range_reminder_shortfall than for range_reminder", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [
        { ...baseNotification, id: "n1", title: "Normal reminder", type: "range_reminder" },
        { ...baseNotification, id: "n2", title: "Shortfall reminder", type: "range_reminder_shortfall" },
      ],
      total: 2,
    });
    renderBell();
    const bellButton = await screen.findByTestId("notification-bell");
    bellButton.click();
    const normalRow = await screen.findByText("Normal reminder");
    const shortfallRow = await screen.findByText("Shortfall reminder");
    expect(normalRow.closest("div")?.parentElement?.textContent).toContain("🔔");
    expect(shortfallRow.closest("div")?.parentElement?.textContent).toContain("⚠️");
  });

  it("opens the bug report modal instead of navigating for a bug_report notification", async () => {
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({
      items: [{ ...baseNotification, id: "n1", title: "תגובה חדשה", type: "bug_report_comment", reference_type: "bug_report", reference_id: "report-123" }],
      total: 1,
    });
    vi.mocked(notificationsApi.markRead).mockResolvedValue({ ...baseNotification, id: "n1", title: "תגובה חדשה", type: "bug_report_comment", is_read: true });
    vi.mocked(bugReportsApi.getMyBugReports).mockResolvedValue({
      items: [{
        id: "report-123", reporter_id: "s1", description: "the modal opened", severity: "low", status: "open",
        route: "/", nav_history: null, audit_snapshot: null, user_snapshot: null, has_screenshot: false,
        created_at: "2026-08-01T10:00:00Z", updated_at: "2026-08-01T10:00:00Z",
        comment_count: 0, last_comment_at: null, has_unseen_activity: true,
      }],
      total: 1,
    });
    vi.mocked(bugReportsApi.listComments).mockResolvedValue([]);

    renderBell();
    (await screen.findByTestId("notification-bell")).click();
    (await screen.findByText("תגובה חדשה")).click();

    expect(await screen.findByText("the modal opened")).toBeInTheDocument();
  });
});
