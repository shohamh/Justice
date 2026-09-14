import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../../auth/AuthContext";
import { listEffectiveDuties } from "../../api/assignments";
import { getSystemSettings } from "../../api/systemSettings";
import AlertBanners from "./AlertBanners";

const mocks = vi.hoisted(() => ({ t: (key: string) => key }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mocks.t }),
}));

vi.mock("../../api/assignments", () => ({ listEffectiveDuties: vi.fn().mockResolvedValue([]) }));
vi.mock("../../api/systemSettings", () => ({ getSystemSettings: vi.fn().mockResolvedValue({}) }));

vi.mock("../../auth/AuthContext", () => ({
  useAuth: vi.fn(() => ({ user: null })),
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
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the alal banner only when alal_relevant is true, regardless of is_officer/is_career", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { is_officer: false, is_career: false, alal_relevant: true },
    } as ReturnType<typeof useAuth>);

    render(
      <AlertBanners lastMitvahimDate={null} lastAlalDate={null} settings={{}} duties={[]} />,
      { wrapper: makeWrapper() },
    );

    expect(screen.getByText(/אל"ל/)).toBeInTheDocument();
  });

  it("hides the alal banner when alal_relevant is false even for an officer", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { is_officer: true, is_career: false, alal_relevant: false },
    } as ReturnType<typeof useAuth>);

    render(
      <AlertBanners lastMitvahimDate={null} lastAlalDate={null} settings={{}} duties={[]} />,
      { wrapper: makeWrapper() },
    );

    expect(screen.queryByText(/אל"ל/)).not.toBeInTheDocument();
  });
  it("does not reject when the settings response is undefined", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { is_officer: false, is_career: false, alal_relevant: false },
    } as ReturnType<typeof useAuth>);
    render(
      <AlertBanners lastMitvahimDate={null} lastAlalDate={null} settings={{}} duties={[]} />,
      { wrapper: makeWrapper() },
    );

    expect(getSystemSettings).not.toHaveBeenCalled();
  });

  it("uses supplied duties and settings without refetching homepage data", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { is_officer: false, is_career: false, alal_relevant: false },
    } as ReturnType<typeof useAuth>);

    const today = new Date();
    const startDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    render(
      <AlertBanners
        lastMitvahimDate={null}
        lastAlalDate={null}
        settings={{ "alerts.upcoming_duty_days": 3 }}
        duties={[
          {
            assignment_id: "assignment-1",
            start_date: startDate,
          } as never,
        ]}
      />,
      { wrapper: makeWrapper() },
    );

    expect(screen.getByText(/upcoming_duty_alert.title/)).toBeInTheDocument();
    expect(listEffectiveDuties).not.toHaveBeenCalled();
    expect(getSystemSettings).not.toHaveBeenCalled();
  });
});
