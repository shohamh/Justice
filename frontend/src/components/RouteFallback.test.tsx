import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import "../i18n";
import RouteFallback from "./RouteFallback";

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({ useAuth: () => mockUseAuth() }));
const mockSettings = vi.fn();
vi.mock("../hooks/usePublicSettings", () => ({ usePublicSettings: () => mockSettings() }));
vi.mock("./Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="layout-shell"><nav data-testid="sidebar" />{children}</div>
  ),
}));

beforeEach(() => {
  mockSettings.mockReturnValue({ "telegram.enabled": true });
});

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

  it("shows only the plain loading status when Telegram linking is required and missing (the user is about to be redirected)", () => {
    renderFallback({ loggedIn: true, authLoading: false, mustChangePassword: false, telegramRequired: true, telegramLinked: false });
    expect(screen.queryByTestId("layout-shell")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("keeps the shell when Telegram linking is required and already linked", () => {
    renderFallback({ loggedIn: true, authLoading: false, mustChangePassword: false, telegramRequired: true, telegramLinked: true });
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
  });

  it("keeps the shell when Telegram linking is not required", () => {
    renderFallback({ loggedIn: true, authLoading: false, mustChangePassword: false, telegramRequired: false, telegramLinked: false });
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
  });

  it("keeps the shell when the Telegram feature is disabled (TelegramGate does not redirect)", () => {
    mockSettings.mockReturnValue({ "telegram.enabled": false });
    renderFallback({ loggedIn: true, authLoading: false, mustChangePassword: false, telegramRequired: true, telegramLinked: false });
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
  });

  it("keeps the shell while public settings are still loading (TelegramGate lets the user through)", () => {
    mockSettings.mockReturnValue(null);
    renderFallback({ loggedIn: true, authLoading: false, mustChangePassword: false, telegramRequired: true, telegramLinked: false });
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
  });
});
