import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import ResetPasswordPage from "./ResetPasswordPage";
import * as authApi from "../api/auth";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../api/auth");

function LocationProbe() {
  const { pathname, search, hash } = useLocation();
  return <output data-testid="route">{pathname + search + hash}</output>;
}

beforeEach(() => vi.clearAllMocks());

it("removes the reset token and fragment while preserving language and submitting the captured token", async () => {
  vi.mocked(authApi.resetPassword).mockResolvedValue(undefined);
  render(
    <MemoryRouter initialEntries={["/reset-password?token=reset-secret&lang=he#old"]}>
      <LocationProbe />
      <ResetPasswordPage />
    </MemoryRouter>,
  );

  await waitFor(() => expect(screen.getByTestId("route")).toHaveTextContent("/reset-password?lang=he"));
  expect(screen.getByTestId("route")).toHaveTextContent(/^\/reset-password\?lang=he$/);

  fireEvent.change(screen.getByLabelText("reset_password.new_password"), { target: { value: "Secure123!" } });
  fireEvent.change(screen.getByLabelText("reset_password.confirm"), { target: { value: "Secure123!" } });
  fireEvent.click(screen.getByRole("button", { name: "reset_password.submit" }));
  await waitFor(() => expect(authApi.resetPassword).toHaveBeenCalledWith("reset-secret", "Secure123!"));
  expect(authApi.resetPassword).toHaveBeenCalledTimes(1);
});
