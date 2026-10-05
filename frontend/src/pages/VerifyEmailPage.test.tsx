import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import VerifyEmailPage from "./VerifyEmailPage";
import * as authApi from "../api/auth";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../api/auth");

function LocationProbe() {
  const { pathname, search, hash } = useLocation();
  return <output data-testid="route">{pathname + search + hash}</output>;
}

beforeEach(() => vi.clearAllMocks());

it("removes the verification token and fragment while preserving language and verifying the captured token", async () => {
  vi.mocked(authApi.verifyEmail).mockResolvedValue(undefined);
  render(
    <MemoryRouter initialEntries={["/verify-email?token=verify-secret&lang=he#old"]}>
      <LocationProbe />
      <VerifyEmailPage />
    </MemoryRouter>,
  );

  await waitFor(() => expect(screen.getByTestId("route")).toHaveTextContent(/^\/verify-email\?lang=he$/));
  await waitFor(() => expect(authApi.verifyEmail).toHaveBeenCalledWith("verify-secret"));
  expect(authApi.verifyEmail).toHaveBeenCalledTimes(1);
  expect(screen.getByText("verify_email.success")).toBeInTheDocument();
});
