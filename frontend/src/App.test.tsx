import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
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

vi.mock("./pages/RangesPage", () => ({
  default: () => <div data-testid="ranges-page" />,
}));

vi.mock("./pages/ImportSessionReviewPage", () => ({
  default: () => <div data-testid="import-session-review-page" />,
}));

vi.mock("./pages/admin/AdminSettingsPage", () => ({
  default: () => <div data-testid="admin-settings-page" />,
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

// The lazy-route Suspense fallback renders the app shell (Layout) for signed-in
// users; routing tests don't need its providers/data fetching.
vi.mock("./components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const mockUsePublicSettings = vi.fn();
vi.mock("./hooks/usePublicSettings", () => ({
  usePublicSettings: () => mockUsePublicSettings(),
}));

beforeEach(() => {
  mockUsePublicSettings.mockReset();
  mockUseAuth.mockReset();
  window.sessionStorage.clear();
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
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="router-location">{`${location.pathname}${location.search}${location.hash}`}</output>;
}

describe("App - forced callup gating", () => {
  it("mounts the hakpaza route when forced_callup.enabled is not false", async () => {
    mockUsePublicSettings.mockReturnValue({ "forced_callup.enabled": true });
    render(
      <MemoryRouter initialEntries={["/commander/hakpaza"]}>
        <App />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("hakpaza-page")).toBeInTheDocument();
  });

  it("does not mount the hakpaza route when forced_callup.enabled is false", async () => {
    mockUsePublicSettings.mockReturnValue({ "forced_callup.enabled": false });
    render(
      <MemoryRouter initialEntries={["/commander/hakpaza"]}>
        <App />
      </MemoryRouter>
    );
    // Unmatched route redirects to the (lazy) home page.
    expect(await screen.findByTestId("home-page")).toBeInTheDocument();
    expect(screen.queryByTestId("hakpaza-page")).not.toBeInTheDocument();
  });
});

describe("App - ranges routing", () => {
  it("keeps the ranges route available while public settings are loading", async () => {
    mockUsePublicSettings.mockReturnValue(null);
    renderApp("/ranges");

    expect(await screen.findByTestId("ranges-page")).toBeInTheDocument();
  });
});

describe("App - retired command dashboard route", () => {
  it("does not register the old command dashboard path", async () => {
    mockUsePublicSettings.mockReturnValue({});
    renderApp("/command-dashboard");

    expect(await screen.findByTestId("home-page")).toBeInTheDocument();
  });
});

describe("App - internal route targets", () => {
  it("resumes a stored internal destination with query and hash after AppGate passes", async () => {
    mockUsePublicSettings.mockReturnValue({});
    const returnPath = "/import/sessions/session-42?tab=summary#details";
    window.sessionStorage.setItem("justice.auth.return-to", returnPath);
    renderApp("/");

    expect(await screen.findByTestId("import-session-review-page")).toBeInTheDocument();
    expect(screen.getByTestId("router-location")).toHaveTextContent(returnPath);
    expect(window.sessionStorage.getItem("justice.auth.return-to")).toBeNull();
  });

  it.each([
    ["external URL", "https://attacker.example/steal"],
    ["protocol-relative URL", "//attacker.example/steal"],
    ["backslash path", "/\\attacker.example/steal"],
    ["control character", "/profile\u0000"],
    ["malformed path", "not-a-path"],
  ])("discards a tampered %s stored target", async (_label, returnPath) => {
    mockUsePublicSettings.mockReturnValue({});
    window.sessionStorage.setItem("justice.auth.return-to", returnPath);
    renderApp("/");

    expect(screen.getByTestId("home-page")).toBeInTheDocument();
    expect(screen.getByTestId("router-location")).toHaveTextContent("/");
    await waitFor(() => expect(window.sessionStorage.getItem("justice.auth.return-to")).toBeNull());
  });

  it("consumes an unknown local target before the catch-all redirects home", async () => {
    mockUsePublicSettings.mockReturnValue({});
    window.sessionStorage.setItem("justice.auth.return-to", "/stale-bookmark?from=oidc");
    renderApp("/");

    await waitFor(() => expect(screen.getByTestId("router-location")).toHaveTextContent("/"));
    expect(screen.getByTestId("home-page")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("justice.auth.return-to")).toBeNull();
  });

  it("does not consume the target while Telegram settings are still loading", () => {
    mockUsePublicSettings.mockReturnValue(null);
    const returnPath = "/profile?tab=notifications";
    window.sessionStorage.setItem("justice.auth.return-to", returnPath);
    renderApp("/");

    expect(screen.getByTestId("home-page")).toBeInTheDocument();
    expect(screen.getByTestId("router-location")).toHaveTextContent("/");
    expect(window.sessionStorage.getItem("justice.auth.return-to")).toBe(returnPath);
  });

  it("keeps the target until the forced-password gate has passed", async () => {
    mockUsePublicSettings.mockReturnValue({});
    mockUseAuth.mockReturnValue({
      loggedIn: true,
      authLoading: false,
      mustChangePassword: true,
      telegramRequired: false,
      telegramLinked: true,
    });
    window.sessionStorage.setItem("justice.auth.return-to", "/profile?tab=security");
    renderApp("/");

    await waitFor(() => expect(screen.getByTestId("router-location")).toHaveTextContent("/change-password"));
    expect(window.sessionStorage.getItem("justice.auth.return-to")).toBe("/profile?tab=security");
  });

  it("keeps the target until the required Telegram gate has passed", async () => {
    mockUsePublicSettings.mockReturnValue({ "telegram.enabled": true });
    mockUseAuth.mockReturnValue({
      loggedIn: true,
      authLoading: false,
      mustChangePassword: false,
      telegramRequired: true,
      telegramLinked: false,
    });
    window.sessionStorage.setItem("justice.auth.return-to", "/profile?tab=notifications");
    renderApp("/");

    await waitFor(() => expect(screen.getByTestId("router-location")).toHaveTextContent("/setup/telegram"));
    expect(window.sessionStorage.getItem("justice.auth.return-to")).toBe("/profile?tab=notifications");
  });

  it("renders a nested protected route and keeps its internal query in the return path", () => {
    mockUsePublicSettings.mockReturnValue({});
    renderApp("/import/sessions/session-42?tab=summary");

    expect(screen.getByTestId("import-session-review-page")).toBeInTheDocument();
    expect(screen.getByTestId("router-location")).toHaveTextContent("/import/sessions/session-42?tab=summary");
    expect(window.location.origin).toBe("http://localhost:3000");
  });

  it("redirects legacy settings URLs to the internal destination with its query", async () => {
    mockUsePublicSettings.mockReturnValue({});
    renderApp("/admin/invite-codes");

    expect(await screen.findByTestId("admin-settings-page")).toBeInTheDocument();
    expect(screen.getByTestId("router-location")).toHaveTextContent("/admin/settings?tab=1");
    expect(window.location.origin).toBe("http://localhost:3000");
  });

  it("redirects an unknown URL internally to home", () => {
    mockUsePublicSettings.mockReturnValue({});
    renderApp("/not-a-route?next=https%3A%2F%2Fevil.example");

    expect(screen.getByTestId("home-page")).toBeInTheDocument();
    expect(screen.getByTestId("router-location")).toHaveTextContent("/");
    expect(screen.getByTestId("router-location")).not.toHaveTextContent("evil.example");
    expect(window.location.origin).toBe("http://localhost:3000");
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

  it("does not redirect away from home while settings are still loading, even if telegramRequired is true", async () => {
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
    expect(await screen.findByTestId("home-page")).toBeInTheDocument();
    expect(screen.queryByText("חיבור טלגרם")).not.toBeInTheDocument();
  });
});
