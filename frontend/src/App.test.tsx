import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";

// Real AuthProvider hits the network on mount (refresh + fetchMe). Replace the
// whole module with a lightweight stand-in so the route tree under test
// (which needs a logged-in, gate-passing user) renders synchronously.
vi.mock("./auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({
    loggedIn: true,
    authLoading: false,
    mustChangePassword: false,
    telegramRequired: false,
    telegramLinked: true,
  }),
}));

vi.mock("./pages/HakpazaPage", () => ({
  default: () => <div data-testid="hakpaza-page" />,
}));

const mockUsePublicSettings = vi.fn();
vi.mock("./hooks/usePublicSettings", () => ({
  usePublicSettings: () => mockUsePublicSettings(),
}));

beforeEach(() => {
  mockUsePublicSettings.mockReset();
});

describe("App - forced callup gating", () => {
  it("mounts the hakpaza route when forced_callup.enabled is not false", () => {
    mockUsePublicSettings.mockReturnValue({ "forced_callup.enabled": true });
    render(
      <MemoryRouter initialEntries={["/commander/hakpaza"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId("hakpaza-page")).toBeInTheDocument();
  });

  it("does not mount the hakpaza route when forced_callup.enabled is false", () => {
    mockUsePublicSettings.mockReturnValue({ "forced_callup.enabled": false });
    render(
      <MemoryRouter initialEntries={["/commander/hakpaza"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.queryByTestId("hakpaza-page")).not.toBeInTheDocument();
  });
});
