import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ForgotPasswordPage from "./ForgotPasswordPage";
import * as authApi from "../api/auth";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../api/auth");

beforeEach(() => {
  vi.clearAllMocks();
});

function renderPage() {
  render(
    <MemoryRouter>
      <ForgotPasswordPage />
    </MemoryRouter>
  );
}

describe("ForgotPasswordPage", () => {
  it("shows the available channels after a successful lookup", async () => {
    vi.mocked(authApi.checkForgotPasswordChannels).mockResolvedValue(["telegram", "email"]);
    renderPage();

    fireEvent.change(screen.getByLabelText("forgot_password.personal_number_label"), { target: { value: "1234567" } });
    fireEvent.click(screen.getByText("forgot_password.continue"));

    expect(await screen.findByText("forgot_password.send_telegram")).toBeInTheDocument();
    expect(screen.getByText("forgot_password.send_email")).toBeInTheDocument();
  });

  // checkForgotPasswordChannels only rejects on a genuine request failure; a
  // malformed-but-200 response (e.g. the channels field missing or not an
  // array) used to flow straight into state typed as string[], crashing the
  // channels.map() call in the "choose channel" step. It should instead
  // degrade to the page's existing "no channels" copy.
  it("treats a malformed channels response as an empty list instead of crashing", async () => {
    vi.mocked(authApi.checkForgotPasswordChannels).mockResolvedValue(
      { channels: "not-an-array" } as unknown as never
    );
    renderPage();

    fireEvent.change(screen.getByLabelText("forgot_password.personal_number_label"), { target: { value: "1234567" } });
    fireEvent.click(screen.getByText("forgot_password.continue"));

    await waitFor(() => expect(authApi.checkForgotPasswordChannels).toHaveBeenCalled());
    expect(await screen.findByText("forgot_password.no_channels")).toBeInTheDocument();
  });
});
