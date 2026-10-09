import { beforeEach, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ADMIN_SETTINGS_TAB_ORDER } from "./AdminSettingsPage";
import AdminSettingsPage from "./AdminSettingsPage";
import { getAdminBugReportUnreadCount, getAdminErrorUnreadCount } from "../../api/bugReports";

let mockPublicSettings: Record<string, unknown> | null = {};
vi.mock("../../hooks/usePublicSettings", () => ({
  usePublicSettings: () => mockPublicSettings,
}));
vi.mock("../../api/bugReports", () => ({
  getAdminErrorUnreadCount: vi.fn().mockResolvedValue(0),
  getAdminBugReportUnreadCount: vi.fn().mockResolvedValue(0),
}));
vi.mock("../../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../SystemSettingsPage", () => ({
  SystemSettingsContent: () => null,
  ChangelogContent: () => null,
}));
vi.mock("../AdminInviteCodesPage", () => ({ AdminInviteCodesContent: () => null }));
vi.mock("./BugReportsContent", () => ({ BugReportsContent: () => null }));
vi.mock("./AuditLogContent", () => ({ default: () => null }));
vi.mock("./HrSyncReviewContent", () => ({ default: () => null }));
vi.mock("./IdentityConflictsContent", () => ({ default: () => null }));
vi.mock("./ExchangeCalendarSyncContent", () => ({ default: () => null }));
vi.mock("./ErrorsContent", () => ({ ErrorsContent: () => null }));

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><AdminSettingsPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

it("places the errors tab immediately before the audit log tab", () => {
  expect(ADMIN_SETTINGS_TAB_ORDER.indexOf("errors")).toBeLessThan(ADMIN_SETTINGS_TAB_ORDER.indexOf("audit-log"));
});

it("places the audit log tab immediately before the hr-sync tab", () => {
  expect(ADMIN_SETTINGS_TAB_ORDER.indexOf("audit-log")).toBeLessThan(ADMIN_SETTINGS_TAB_ORDER.indexOf("hr-sync"));
});

it("places the identity-conflicts tab after hr-sync, matching the tab index the page renders", () => {
  expect(ADMIN_SETTINGS_TAB_ORDER.indexOf("identity-conflicts")).toBe(ADMIN_SETTINGS_TAB_ORDER.indexOf("hr-sync") + 1);
  expect(ADMIN_SETTINGS_TAB_ORDER.indexOf("identity-conflicts")).toBe(7);
});

beforeEach(() => {
  vi.mocked(getAdminErrorUnreadCount).mockClear();
  vi.mocked(getAdminBugReportUnreadCount).mockClear();
});

it("does not request the error-log unread count when no log source is configured", async () => {
  mockPublicSettings = { "errors.log_source_configured": false };
  renderPage();
  await waitFor(() => expect(getAdminBugReportUnreadCount).toHaveBeenCalled());
  expect(getAdminErrorUnreadCount).not.toHaveBeenCalled();
});

it("requests the error-log unread count when a log source is configured", async () => {
  mockPublicSettings = { "errors.log_source_configured": true };
  renderPage();
  await waitFor(() => expect(getAdminErrorUnreadCount).toHaveBeenCalledTimes(1));
});

it("does not request it while public settings are still loading", async () => {
  mockPublicSettings = null;
  renderPage();
  await waitFor(() => expect(getAdminBugReportUnreadCount).toHaveBeenCalled());
  expect(getAdminErrorUnreadCount).not.toHaveBeenCalled();
});

it("does not request it when settings failed to load (empty map means unknown)", async () => {
  mockPublicSettings = {};
  renderPage();
  await waitFor(() => expect(getAdminBugReportUnreadCount).toHaveBeenCalled());
  expect(getAdminErrorUnreadCount).not.toHaveBeenCalled();
});
