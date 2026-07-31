import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./i18n";
import App from "./App";

// Real AuthProvider hits the network on mount (refresh + fetchMe). Replace the
// whole module with a lightweight stand-in so the route tree under test
// (which needs a logged-in, gate-passing user) renders synchronously.
const mockUseAuth = vi.fn();
vi.mock("./auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => mockUseAuth(),
}));

vi.mock("./pages/HakpazaPage", () => ({
  default: () => <div data-testid="hakpaza-page" />,
}));

// HomePage pulls in a deep tree (Layout/UnifiedNav -> AlgorithmSeenContext,
// plus several data-fetching widgets) that isn't relevant to routing/gating
// behavior — stub it so the TelegramGate tests below can render "/" without
// wiring up every provider HomePage transitively needs.
vi.mock("./pages/HomePage", () => ({
  default: () => <div data-testid="home-page" />,
}));

// TelegramSetupPage fires a real network call on mount (generateTelegramCode)
// via react-query — stub the api module so the routing test doesn't depend on
// a live backend, and never resolves so the "loading" state (default page
// content) stays stable for the assertion.
vi.mock("./api/telegram", () => ({
  generateTelegramCode: vi.fn(() => new Promise(() => {})),
  getTelegramStatus: vi.fn(() => new Promise(() => {})),
}));

const mockUsePublicSettings = vi.fn();
vi.mock("./hooks/usePublicSettings", () => ({
  usePublicSettings: () => mockUsePublicSettings(),
}));

beforeEach(() => {
  mockUsePublicSettings.mockReset();
  mockUseAuth.mockReset();
  mockUseAuth.mockReturnValue({
    loggedIn: true,
    authLoading: false,
    mustChangePassword: false,
    telegramRequired: false,
    telegramLinked: true,
  });
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })));
});

function renderApp(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

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

describe("TelegramGate routing", () => {
  it("renders the actual TelegramSetupPage content when settings are still loading and telegramRequired is true", async () => {
    mockUseAuth.mockReturnValue({
      loggedIn: true,
      authLoading: false,
      mustChangePassword: false,
      telegramRequired: true,
      telegramLinked: false,
    });
    // Simulates settings still loading (usePublicSettings returns null until
    // the /settings/public fetch resolves).
    mockUsePublicSettings.mockReturnValue(null);
    renderApp("/setup/telegram");
    // Real, specific content from TelegramSetupPage.tsx (t("telegram_setup.title"),
    // he.json: "חיבור טלגרם") — not a generic "body is not empty" check, so this
    // fails if the wrong route/page renders.
    expect(await screen.findByText("חיבור טלגרם")).toBeInTheDocument();
  });

  it("does not redirect away from home while settings are still loading, even if telegramRequired is true", () => {
    mockUseAuth.mockReturnValue({
      loggedIn: true,
      authLoading: false,
      mustChangePassword: false,
      telegramRequired: true,
      telegramLinked: false,
    });
    mockUsePublicSettings.mockReturnValue(null);
    renderApp("/");
    // TelegramGate must wait for settings to load before redirecting, so the
    // gated child route (HomePage, stubbed above) stays mounted instead of
    // bouncing to /setup/telegram.
    expect(screen.getByTestId("home-page")).toBeInTheDocument();
    expect(screen.queryByText("חיבור טלגרם")).not.toBeInTheDocument();
  });
});
