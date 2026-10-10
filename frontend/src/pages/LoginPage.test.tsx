import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { AxiosError } from "axios";
import LoginPage from "./LoginPage";
import * as authApi from "../api/auth";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) => opts ? `${key}:${JSON.stringify(opts)}` : key }),
}));

const mockLogin = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ login: mockLogin }),
}));

vi.mock("../components/JusticeLogo", () => ({ default: () => null }));
vi.mock("../api/auth");

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  vi.mocked(authApi.fetchOidcStatus).mockResolvedValue(false);
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="current-location">{`${location.pathname}${location.search}${location.hash}`}</output>;
}

async function submitValidLogin(initialEntry: { pathname: string; state?: unknown }) {
  const originalOrigin = window.location.origin;
  mockLogin.mockResolvedValueOnce(undefined);
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LocationProbe />
      <LoginPage />
    </MemoryRouter>,
  );
  fireEvent.change(screen.getByTestId("personal-number-input"), { target: { value: "123" } });
  fireEvent.change(screen.getByTestId("password-input"), { target: { value: "password" } });
  fireEvent.submit(screen.getByTestId("login-form"));
  await waitFor(() => expect(screen.getByTestId("current-location")).not.toHaveTextContent("/login"));
  return originalOrigin;
}

describe("remember me", () => {
  async function submit() {
    mockLogin.mockResolvedValueOnce(undefined);
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    fireEvent.change(screen.getByTestId("personal-number-input"), { target: { value: "123" } });
    fireEvent.change(screen.getByTestId("password-input"), { target: { value: "password" } });
    fireEvent.submit(screen.getByTestId("login-form"));
    await waitFor(() => expect(mockLogin).toHaveBeenCalledTimes(1));
  }

  it("is ticked by default and logs in with remember_me true", async () => {
    await submit();
    expect(screen.getByTestId("remember-me-checkbox")).toBeChecked();
    expect(mockLogin).toHaveBeenCalledWith("123", "password", true);
  });

  it("logs in with remember_me false when unticked", async () => {
    mockLogin.mockResolvedValueOnce(undefined);
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    fireEvent.click(screen.getByTestId("remember-me-checkbox"));
    fireEvent.change(screen.getByTestId("personal-number-input"), { target: { value: "123" } });
    fireEvent.change(screen.getByTestId("password-input"), { target: { value: "password" } });
    fireEvent.submit(screen.getByTestId("login-form"));
    await waitFor(() => expect(mockLogin).toHaveBeenCalledWith("123", "password", false));
  });

  it("SSO button carries the choice: true by default, false when unticked", async () => {
    vi.mocked(authApi.fetchOidcStatus).mockResolvedValue(true);
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    const sso = await screen.findByTestId("sso-login-button");
    fireEvent.click(sso);
    expect(authApi.startSsoLogin).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByTestId("remember-me-checkbox"));
    fireEvent.click(sso);
    expect(authApi.startSsoLogin).toHaveBeenLastCalledWith(false);
  });
});

describe("password login return target", () => {
  it("persists a saved internal path with its query and hash for AppGate", async () => {
    const originalOrigin = await submitValidLogin({
      pathname: "/login",
      state: { from: { pathname: "/import/sessions/session-42", search: "?tab=summary", hash: "#details" } },
    });

    expect(screen.getByTestId("current-location")).toHaveTextContent("/");
    expect(window.sessionStorage.getItem("justice.auth.return-to")).toBe("/import/sessions/session-42?tab=summary#details");
    expect(window.location.origin).toBe(originalOrigin);
  });

  it("falls back to the home page when no return target was saved", async () => {
    const originalOrigin = await submitValidLogin({ pathname: "/login" });

    expect(screen.getByTestId("current-location")).toHaveTextContent("/");
    expect(window.sessionStorage.getItem("justice.auth.return-to")).toBeNull();
    expect(window.location.origin).toBe(originalOrigin);
  });

  it("keeps the stored safe target available to password login after an SSO error", async () => {
    const returnPath = "/profile?tab=notifications#telegram";
    window.sessionStorage.setItem("justice.auth.return-to", returnPath);
    mockLogin.mockResolvedValueOnce(undefined);
    render(
      <MemoryRouter initialEntries={["/login?sso_error=1"]}>
        <LocationProbe />
        <LoginPage />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByTestId("personal-number-input"), { target: { value: "123" } });
    fireEvent.change(screen.getByTestId("password-input"), { target: { value: "password" } });
    fireEvent.submit(screen.getByTestId("login-form"));

    await waitFor(() => expect(screen.getByTestId("current-location")).toHaveTextContent("/"));
    expect(window.sessionStorage.getItem("justice.auth.return-to")).toBe(returnPath);
  });

  it("keeps the reset-password success banner when router state also carries a return path", async () => {
    render(
      <MemoryRouter initialEntries={[{
        pathname: "/login",
        state: { resetSuccess: true, from: { pathname: "/profile", search: "?tab=security", hash: "" } },
      }] }>
        <LoginPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("reset_password.success")).toBeInTheDocument();
  });

  it.each([
    ["absolute external", "https://attacker.example/steal"],
    ["protocol-relative", "//attacker.example/steal"],
    ["backslash path", "/\\attacker.example/steal"],
    ["control character", "/profile\u0000"],
    ["non-string", 42],
  ])("rejects a %s return target", async (_label, target) => {
    const originalOrigin = await submitValidLogin({ pathname: "/login", state: { from: target } });

    expect(screen.getByTestId("current-location")).toHaveTextContent("/");
    expect(window.location.origin).toBe(originalOrigin);
  });
});

function makeRateLimitError(retryAfterSeconds: string) {
  const err = new AxiosError("rate limited");
  err.response = {
    status: 429,
    headers: { "retry-after": retryAfterSeconds },
    data: {},
    statusText: "Too Many Requests",
    // @ts-expect-error partial mock
    config: {},
  };
  return err;
}

test("shows retry-after seconds when login is rate limited", async () => {
  mockLogin.mockRejectedValueOnce(makeRateLimitError("42"));
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  fireEvent.change(screen.getByTestId("personal-number-input"), { target: { value: "123" } });
  fireEvent.change(screen.getByTestId("password-input"), { target: { value: "password" } });
  const form = screen.getByTestId("login-form");
  fireEvent.submit(form);
  await waitFor(() => {
    expect(screen.getByText(/login.errors.rate_limited/)).toHaveTextContent('"seconds":"42"');
  });
});

function makeInvalidCredentialsError(attempts: number, maxAttempts: number) {
  const err = new AxiosError("invalid credentials");
  err.response = {
    status: 401,
    headers: {},
    data: { detail: { detail: "invalid_credentials", attempts, max_attempts: maxAttempts } },
    statusText: "Unauthorized",
    // @ts-expect-error partial mock
    config: {},
  };
  return err;
}

test("shows attempt count against the lockout limit on invalid credentials", async () => {
  mockLogin.mockRejectedValueOnce(makeInvalidCredentialsError(3, 10));
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  fireEvent.change(screen.getByTestId("personal-number-input"), { target: { value: "123" } });
  fireEvent.change(screen.getByTestId("password-input"), { target: { value: "password" } });
  const form = screen.getByTestId("login-form");
  fireEvent.submit(form);
  await waitFor(() => {
    expect(screen.getByText(/login.errors.attempts_remaining/)).toHaveTextContent('"n":3');
    expect(screen.getByText(/login.errors.attempts_remaining/)).toHaveTextContent('"max":10');
  });
});

function makeValidationError() {
  const err = new AxiosError("unprocessable");
  err.response = {
    status: 422,
    headers: {},
    data: { detail: [{ msg: "String should match pattern", loc: ["body", "personal_number"] }] },
    statusText: "Unprocessable Entity",
    // @ts-expect-error partial mock
    config: {},
  };
  return err;
}

test("shows the invalid-credentials message, not a generic network error, for a malformed username", async () => {
  mockLogin.mockRejectedValueOnce(makeValidationError());
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  fireEvent.change(screen.getByTestId("personal-number-input"), { target: { value: "abc" } });
  fireEvent.change(screen.getByTestId("password-input"), { target: { value: "password" } });
  const form = screen.getByTestId("login-form");
  fireEvent.submit(form);
  await waitFor(() => {
    expect(screen.getByText("login.errors.invalid_credentials")).toBeInTheDocument();
  });
  expect(screen.queryByText("login.errors.network")).not.toBeInTheDocument();
});

describe("SSO login", () => {
  it("hides the SSO button when the server reports SSO disabled", async () => {
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    await waitFor(() => expect(authApi.fetchOidcStatus).toHaveBeenCalled());
    expect(screen.queryByTestId("sso-login-button")).toBeNull();
    expect(screen.getByTestId("login-form")).toBeInTheDocument();
  });

  it("shows the SSO button when enabled and keeps password login usable", async () => {
    vi.mocked(authApi.fetchOidcStatus).mockResolvedValue(true);
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    expect(await screen.findByTestId("sso-login-button")).toBeInTheDocument();
    expect(screen.getByTestId("personal-number-input")).toBeInTheDocument();
    expect(screen.getByTestId("password-input")).toBeInTheDocument();
    expect(screen.getByTestId("login-submit")).toBeInTheDocument();
  });

  it("starts SSO with a top-level navigation when the button is clicked", async () => {
    vi.mocked(authApi.fetchOidcStatus).mockResolvedValue(true);
    const returnPath = "/import/sessions/session-42?tab=summary#details";
    vi.mocked(authApi.startSsoLogin).mockImplementation(() => {
      expect(window.sessionStorage.getItem("justice.auth.return-to")).toBe(returnPath);
    });
    render(
      <MemoryRouter initialEntries={[{
        pathname: "/login",
        state: { from: { pathname: "/import/sessions/session-42", search: "?tab=summary", hash: "#details" } },
      }] }>
        <LoginPage />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTestId("sso-login-button"));
    expect(authApi.startSsoLogin).toHaveBeenCalledTimes(1);
    expect(authApi.startSsoLogin).toHaveBeenCalledWith(true);
    vi.mocked(authApi.startSsoLogin).mockReset();
  });

  it("still starts SSO when session storage rejects the return-path write", async () => {
    vi.mocked(authApi.fetchOidcStatus).mockResolvedValue(true);
    const setItem = vi.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
      throw new DOMException("Storage is blocked", "SecurityError");
    });
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    fireEvent.click(await screen.findByTestId("sso-login-button"));

    expect(authApi.startSsoLogin).toHaveBeenCalledWith(true);
    setItem.mockRestore();
  });

  it("shows only a generic banner for ?sso_error=1 and echoes nothing else", async () => {
    render(
      <MemoryRouter initialEntries={["/login?sso_error=1&code=SECRET&email=x@y.z"]}>
        <LoginPage />
      </MemoryRouter>,
    );
    const banner = await screen.findByTestId("sso-error");
    expect(banner).toHaveTextContent("login.errors.sso_failed");
    expect(document.body.textContent).not.toContain("SECRET");
    expect(document.body.textContent).not.toContain("x@y.z");
  });

  it("shows no SSO error banner without the sso_error flag", async () => {
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    await waitFor(() => expect(authApi.fetchOidcStatus).toHaveBeenCalled());
    expect(screen.queryByTestId("sso-error")).toBeNull();
  });
});
