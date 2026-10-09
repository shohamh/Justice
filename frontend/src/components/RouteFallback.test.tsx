import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import "../i18n";
import RouteFallback from "./RouteFallback";

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({ useAuth: () => mockUseAuth() }));
vi.mock("./Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="layout-shell"><nav data-testid="sidebar" />{children}</div>
  ),
}));

function renderFallback(auth: object) {
  mockUseAuth.mockReturnValue(auth);
  return render(<MemoryRouter><RouteFallback /></MemoryRouter>);
}

describe("RouteFallback", () => {
  it("keeps the shell around the loading status when signed in", () => {
    renderFallback({ loggedIn: true, authLoading: false, mustChangePassword: false });
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it.each([
    ["signed out", { loggedIn: false, authLoading: false, mustChangePassword: false }],
    ["auth loading", { loggedIn: true, authLoading: true, mustChangePassword: false }],
    ["forced password change", { loggedIn: true, authLoading: false, mustChangePassword: true }],
  ])("shows only the plain loading status when %s", (_n, auth) => {
    renderFallback(auth);
    expect(screen.queryByTestId("layout-shell")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
