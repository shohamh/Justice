/**
 * A login submitted while the startup session restore is still in flight must win.
 *
 * Real AuthProvider + LoginPage + ProtectedRoute + the real api client; only the
 * network (the axios adapter) is faked, so the startup traffic is the same as in
 * the app: the restore's /auth/refresh, and an authenticated startup request
 * (/settings/public, as App's usePublicSettings issues) that waits on the restore,
 * goes out anonymously when it fails, gets a 401 and runs the 401 handler.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from "axios";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../components/JusticeLogo", () => ({ default: () => null }));
vi.mock("../errorReporting", () => ({
  newRequestId: () => "req-id",
  reportAxiosError: vi.fn(),
  setErrorReportingToken: vi.fn(),
}));

type Reply = (status: number, data?: unknown) => void;

function me(id: string) {
  return { id, full_name: id, role: "soldier", must_change_password: false, active_deputy_grants: [] };
}

async function setup() {
  vi.resetModules();
  const client = await import("../api/client");
  const { AuthProvider, useAuth } = await import("./AuthContext");
  const { default: LoginPage } = await import("../pages/LoginPage");
  const { default: ProtectedRoute } = await import("./ProtectedRoute");
  const { getPublicSettings } = await import("../api/publicSettings");

  const pending: Record<string, Reply[]> = {};
  const sent: { url: string; authorization?: string }[] = [];
  const adapter: AxiosAdapter = (config: InternalAxiosRequestConfig) => {
    const url = config.url ?? "";
    const authorization = config.headers?.Authorization as string | undefined;
    sent.push({ url, authorization });
    return new Promise<AxiosResponse>((resolve, reject) => {
      const reply: Reply = (status, data = {}) => {
        const response = { data, status, statusText: String(status), headers: {}, config };
        if (status >= 400) {
          reject(Object.assign(new Error(`status ${status}`), { isAxiosError: true, config, response }));
        } else {
          resolve(response);
        }
      };
      if (url === "/auth/oidc/status") return reply(200, { enabled: false });
      if (url === "/settings/public") return authorization ? reply(200, { settings: {} }) : reply(401);
      if (url === "/me") {
        if (authorization === "Bearer login-token") return reply(200, me("login-user"));
        if (authorization === "Bearer restored-token") return reply(200, me("restored-user"));
        return reply(401);
      }
      // /auth/refresh and /auth/login are answered by the test.
      (pending[url] ??= []).push(reply);
    });
  };
  client.api.defaults.adapter = adapter;

  function StartupRequests() {
    useEffect(() => { void getPublicSettings().catch(() => undefined); }, []);
    return null;
  }
  function Home() {
    const { user } = useAuth();
    return <div data-testid="home">{user?.id}</div>;
  }

  render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <StartupRequests />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<Home />} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );

  const settle = async () => {
    await act(async () => {
      for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0));
    });
  };
  const next = async (url: string): Promise<Reply> => {
    await waitFor(() => expect(pending[url]?.length ?? 0).toBeGreaterThan(0));
    return pending[url]!.shift()!;
  };
  const submitLogin = async () => {
    fireEvent.change(screen.getByTestId("personal-number-input"), { target: { value: "1000001" } });
    fireEvent.change(screen.getByTestId("password-input"), { target: { value: "pw" } });
    fireEvent.submit(screen.getByTestId("login-form"));
    await settle();
  };
  return { client, sent, next, settle, submitLogin };
}

describe("login submitted during the startup session restore", () => {
  it("wins when the restore then fails (no session cookie)", async () => {
    const { next, settle, submitLogin, sent } = await setup();
    const restoreRefresh = await next("/auth/refresh");
    await submitLogin();
    const loginReply = await next("/auth/login");

    // Restore fails after the submit; the waiting startup request goes out
    // anonymously, 401s, its handler refresh fails too.
    restoreRefresh(401);
    await settle();
    (await next("/auth/refresh"))(401);
    await settle();
    expect(sent.filter((s) => s.url === "/settings/public")).toHaveLength(1);

    loginReply(200, { access_token: "login-token", token_type: "bearer", must_change_password: false });
    await waitFor(() => expect(screen.getByTestId("home")).toHaveTextContent("login-user"));
  });

  it("wins over a restore that succeeds for a previous session after the submit", async () => {
    const { next, settle, submitLogin } = await setup();
    const restoreRefresh = await next("/auth/refresh");
    await submitLogin();
    const loginReply = await next("/auth/login");

    restoreRefresh(200, { access_token: "restored-token" });
    await settle();
    loginReply(200, { access_token: "login-token", token_type: "bearer", must_change_password: false });
    await waitFor(() => expect(screen.getByTestId("home")).toHaveTextContent("login-user"));
    await settle();
    expect(screen.getByTestId("home")).toHaveTextContent("login-user");
  });

  it("wins when the restore fails only after the login completed", async () => {
    const { client, next, settle, submitLogin } = await setup();
    const restoreRefresh = await next("/auth/refresh");
    await submitLogin();
    (await next("/auth/login"))(200, { access_token: "login-token", token_type: "bearer", must_change_password: false });
    await waitFor(() => expect(screen.getByTestId("home")).toHaveTextContent("login-user"));

    restoreRefresh(401);
    await settle();
    expect(screen.getByTestId("home")).toHaveTextContent("login-user");
    expect(client.getAccessToken()).toBe("login-token");
  });

  it("still reports a genuinely expired session after the user signed in", async () => {
    const { client, next, settle, submitLogin } = await setup();
    (await next("/auth/refresh"))(401);
    await settle();
    await submitLogin();
    (await next("/auth/login"))(200, { access_token: "login-token", token_type: "bearer", must_change_password: false });
    await waitFor(() => expect(screen.getByTestId("home")).toHaveTextContent("login-user"));

    act(() => { window.dispatchEvent(new Event("auth:session-expired")); });
    await settle();
    expect(screen.queryByTestId("home")).toBeNull();
    expect(screen.getByTestId("login-form")).toBeInTheDocument();
    expect(client.getAccessToken()).toBeNull();
  });
});
