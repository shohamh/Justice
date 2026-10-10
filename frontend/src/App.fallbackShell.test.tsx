import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./i18n";
import App from "./App";

const mockUseAuth = vi.fn();
vi.mock("./auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => mockUseAuth(),
}));
vi.mock("./hooks/usePublicSettings", () => ({ usePublicSettings: () => ({ "telegram.enabled": true }) }));
vi.mock("./components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div><nav data-testid="sidebar" />{children}</div>
  ),
}));

let release: () => void = () => {};
vi.mock("./pages/TransparencyPage", async () => {
  await new Promise<void>((resolve) => { release = resolve; });
  return { default: () => <div data-testid="transparency-page" /> };
});

function renderAt(path: string) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}><App /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("App lazy route fallback", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
  });

  it("keeps the nav visible while the chunk loads, then shows the page", async () => {
    mockUseAuth.mockReturnValue({ loggedIn: true, authLoading: false, mustChangePassword: false, telegramRequired: false, telegramLinked: true });
    renderAt("/transparency");
    expect(await screen.findByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
    await act(async () => { release(); });
    expect(await screen.findByTestId("transparency-page")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows no nav while the chunk loads for a user about to be redirected to Telegram setup", async () => {
    mockUseAuth.mockReturnValue({ loggedIn: true, authLoading: false, mustChangePassword: false, telegramRequired: true, telegramLinked: false });
    renderAt("/transparency");
    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(screen.queryByTestId("sidebar")).not.toBeInTheDocument();
  });
});
