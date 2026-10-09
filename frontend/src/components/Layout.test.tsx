import { render, screen, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { getAdminBugReportUnreadCount, getAdminErrorUnreadCount } from "../api/bugReports";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

function renderLayout(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

const mockCycleTheme = vi.fn();
let mockTheme = "light";
vi.mock("../theme/ThemeContext", () => ({
  useTheme: () => ({ theme: mockTheme, resolvedTheme: "light", cycleTheme: mockCycleTheme }),
}));
let mockRole = "soldier";
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ logout: vi.fn(), user: { role: mockRole } }),
}));
vi.mock("../api/bugReports", () => ({
  getAdminErrorUnreadCount: vi.fn().mockResolvedValue(0),
  getAdminBugReportUnreadCount: vi.fn().mockResolvedValue(0),
}));
vi.mock("../api/publicSettings", () => ({
  getPublicSettings: () => Promise.resolve({}),
}));
let mockPublicSettings: Record<string, unknown> | null = {};
vi.mock("../hooks/usePublicSettings", () => ({
  usePublicSettings: () => mockPublicSettings,
}));
vi.mock("./UnifiedNav", () => ({
  default: () => null,
}));
vi.mock("./HelpModal", () => ({
  default: () => null,
}));
vi.mock("./NotificationBell", () => ({
  default: () => null,
}));
vi.mock("./JusticeLogo", () => ({
  default: () => null,
}));
vi.mock("./BugReportTrigger", () => ({
  default: () => null,
}));

describe("Layout theme toggle", () => {
  it("renders the toggle and calls cycleTheme on click", async () => {
    mockTheme = "light";
    const { default: Layout } = await import("./Layout");
    renderLayout(<Layout>children</Layout>);

    const toggle = screen.getByTestId("theme-toggle-button");
    act(() => toggle.click());
    expect(mockCycleTheme).toHaveBeenCalledTimes(1);
  });
});

describe("Layout logo", () => {
  it("links the header logo to the homepage", async () => {
    const { default: Layout } = await import("./Layout");
    renderLayout(<Layout>children</Layout>);

    const logoLink = document.querySelector('a[href="/"]');
    expect(logoLink).not.toBeNull();
  });
});

describe("Layout admin unread polling", () => {
  beforeEach(() => {
    vi.mocked(getAdminErrorUnreadCount).mockClear();
    vi.mocked(getAdminBugReportUnreadCount).mockClear();
    mockRole = "admin";
  });

  it("does not request the error-log unread count when no log source is configured", async () => {
    mockPublicSettings = { "errors.log_source_configured": false };
    const { default: Layout } = await import("./Layout");
    renderLayout(<Layout>children</Layout>);
    await waitFor(() => expect(getAdminBugReportUnreadCount).toHaveBeenCalled());
    expect(getAdminErrorUnreadCount).not.toHaveBeenCalled();
  });

  it("requests the error-log unread count when a log source is configured", async () => {
    mockPublicSettings = { "errors.log_source_configured": true };
    const { default: Layout } = await import("./Layout");
    renderLayout(<Layout>children</Layout>);
    await waitFor(() => expect(getAdminErrorUnreadCount).toHaveBeenCalledTimes(1));
  });

  it("does not request it while public settings are still loading", async () => {
    mockPublicSettings = null;
    const { default: Layout } = await import("./Layout");
    renderLayout(<Layout>children</Layout>);
    await waitFor(() => expect(getAdminBugReportUnreadCount).toHaveBeenCalled());
    expect(getAdminErrorUnreadCount).not.toHaveBeenCalled();
  });
});
