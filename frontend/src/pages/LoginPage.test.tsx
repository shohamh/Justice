import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AxiosError } from "axios";
import LoginPage from "./LoginPage";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) => opts ? `${key}:${JSON.stringify(opts)}` : key }),
}));

const mockLogin = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ login: mockLogin }),
}));

vi.mock("../components/JusticeLogo", () => ({ default: () => null }));

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
