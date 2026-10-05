import { StrictMode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import ActionPage from "./ActionPage";
import { api } from "../api/client";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../api/client", () => ({ api: { post: vi.fn() } }));

function LocationProbe() {
  const { pathname, search, hash } = useLocation();
  return <output data-testid="route">{pathname + search + hash}</output>;
}

beforeEach(() => vi.clearAllMocks());

it("redeems the captured action token once in StrictMode and removes it from the route", async () => {
  vi.mocked(api.post).mockImplementation(() => new Promise(() => {}));
  render(
    <StrictMode>
      <MemoryRouter initialEntries={["/action?token=action-secret&lang=he#old"]}>
        <LocationProbe />
        <ActionPage />
      </MemoryRouter>
    </StrictMode>,
  );

  await waitFor(() => expect(screen.getByTestId("route")).toHaveTextContent(/^\/action\?lang=he$/));
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith("/action", { token: "action-secret" });
});
