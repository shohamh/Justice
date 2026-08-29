import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useAuth } from "../../auth/AuthContext";
import { getSystemSettings } from "../../api/systemSettings";
import AlertBanners from "./AlertBanners";

const mocks = vi.hoisted(() => ({ t: (key: string) => key }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mocks.t }),
}));

vi.mock("../../auth/AuthContext", () => ({
  useAuth: vi.fn(() => ({ user: null })),
}));

vi.mock("../../api/assignments", () => ({
  listEffectiveDuties: vi.fn().mockResolvedValue([]),
}));

vi.mock("../../api/systemSettings", () => ({
  getSystemSettings: vi.fn().mockResolvedValue({}),
}));

function makeWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

describe("AlertBanners alal gating", () => {
  it("shows the alal banner only when alal_relevant is true, regardless of is_officer/is_career", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { is_officer: false, is_career: false, alal_relevant: true },
    } as ReturnType<typeof useAuth>);

    render(
      <AlertBanners lastMitvahimDate={null} lastAlalDate={null} settings={{}} />,
      { wrapper: makeWrapper() },
    );

    expect(screen.getByText(/אל"ל/)).toBeInTheDocument();
  });

  it("hides the alal banner when alal_relevant is false even for an officer", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { is_officer: true, is_career: false, alal_relevant: false },
    } as ReturnType<typeof useAuth>);

    render(
      <AlertBanners lastMitvahimDate={null} lastAlalDate={null} settings={{}} />,
      { wrapper: makeWrapper() },
    );

    expect(screen.queryByText(/אל"ל/)).not.toBeInTheDocument();
  });
  it("does not reject when the settings response is undefined", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { is_officer: false, is_career: false, alal_relevant: false },
    } as ReturnType<typeof useAuth>);
    vi.mocked(getSystemSettings).mockResolvedValue(undefined as never);

    render(
      <AlertBanners lastMitvahimDate={null} lastAlalDate={null} settings={{}} />,
      { wrapper: makeWrapper() },
    );

    await vi.waitFor(() => expect(getSystemSettings).toHaveBeenCalled());
  });
});
