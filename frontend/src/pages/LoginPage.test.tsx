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
