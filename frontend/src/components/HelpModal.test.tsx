import { describe, expect, it, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { PermissionUser } from "../auth/permissions";
import HelpModal from "./HelpModal";

let mockUser: PermissionUser | null = null;

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: mockUser,
    isLoading: false,
    error: null,
    logout: vi.fn(),
    loggedIn: !!mockUser,
  }),
}));

const setUser = (role: string, overrides: Record<string, unknown> = {}) => {
  mockUser = {
    id: "user-1",
    name: "Test User",
    email: "test@example.com",
    role: role as "soldier" | "duty_manager" | "admin",
    is_commander: false,
    is_duty_manager: false,
    ...overrides,
  };
};

describe("HelpModal", () => {
  afterEach(() => {
    mockUser = null;
  });

  it("Hakpaza tab is visible to commander, hidden from soldier", () => {
    setUser("commander", { is_commander: true });
    const { unmount } = render(<HelpModal onClose={() => {}} gimelimEnabled={false} initialTab="hakpaza" />);
    // Check that commander can see the tab button
    expect(screen.getByRole("button", { name: /הקפצה פיקודית/ })).toBeInTheDocument();
    // Check that the heading is shown when hakpaza tab is active
    expect(screen.getByRole("heading", { name: /הקפצה פיקודית/ })).toBeInTheDocument();

    // Unmount and remount with soldier user
    unmount();
    setUser("soldier");
    render(<HelpModal onClose={() => {}} gimelimEnabled={false} />);
    // Check that soldier can't see the tab button
    expect(screen.queryByRole("button", { name: /הקפצה פיקודית/ })).not.toBeInTheDocument();
    // Check that the heading is not shown
    expect(screen.queryByRole("heading", { name: /הקפצה פיקודית/ })).not.toBeInTheDocument();
  });
});
