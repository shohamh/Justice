import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

function renderLayout(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

const mockCycleTheme = vi.fn();
let mockTheme = "light";
vi.mock("../theme/ThemeContext", () => ({
  useTheme: () => ({ theme: mockTheme, resolvedTheme: "light", cycleTheme: mockCycleTheme }),
}));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ logout: vi.fn(), user: { role: "soldier" } }),
}));
vi.mock("../api/publicSettings", () => ({
  getPublicSettings: () => Promise.resolve({}),
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
