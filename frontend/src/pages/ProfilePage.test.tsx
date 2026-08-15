import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import ProfilePage from "./ProfilePage";
import { useAuth } from "../auth/AuthContext";
import type { Me } from "../api/auth";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("react-router-dom", () => ({ Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a> }));
vi.mock("../auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../components/Layout", () => ({ default: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
vi.mock("../components/ExemptionsPanel", () => ({ default: () => null }));
vi.mock("../components/SoldierLink", () => ({ default: ({ name }: { name: string }) => <span>{name}</span> }));
vi.mock("../components/Combobox", () => ({ default: () => null }));
vi.mock("../components/DateInput", () => ({ default: () => null }));
vi.mock("../hooks/usePublicSettings", () => ({ usePublicSettings: () => null }));
vi.mock("../api/soldiers", () => ({
  submitFieldUpdate: vi.fn(), listFieldUpdates: vi.fn().mockResolvedValue([]), getRanks: vi.fn().mockResolvedValue({ enlisted: [], officers: [] }),
}));
vi.mock("../api/auth", () => ({ setEmail: vi.fn() }));
vi.mock("../api/registrationSettings", () => ({ getRegistrationPublicSettings: vi.fn().mockResolvedValue({}) }));
vi.mock("../api/telegram", () => ({ generateTelegramCode: vi.fn(), getTelegramStatus: vi.fn().mockResolvedValue({}), unlinkTelegram: vi.fn() }));
vi.mock("../api/notifications", () => ({
  getPreferences: vi.fn().mockResolvedValue([]), updatePreferences: vi.fn(), listCommanderScopes: vi.fn().mockResolvedValue([]), addCommanderScope: vi.fn(), removeCommanderScope: vi.fn(),
}));
vi.mock("../api/hierarchy", () => ({ fetchTree: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/rangeStatus", () => ({ getSoldierRangeStatus: vi.fn().mockResolvedValue({ statuses: [] }) }));

const oldUser: Me = {
  id: "soldier-1", personal_number: "12345678", full_name: "ישראל ישראלי", role: "soldier",
  is_commander: false, is_duty_manager: false, must_change_password: false,
  hierarchy_node_id: null, telegram_linked: false, telegram_required: false,
  enrollment_pending: false, theme_preference: "system", last_mitvahim_date: "2026-08-01",
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><ProfilePage /></QueryClientProvider>);
}

describe("ProfilePage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("refreshes the authenticated profile on mount and displays the approved date", async () => {
    const refreshMe = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useAuth).mockReturnValue({ user: oldUser, refreshMe } as ReturnType<typeof useAuth>);

    const page = renderPage();

    await waitFor(() => expect(refreshMe).toHaveBeenCalledTimes(1));
    expect(screen.getByText("01.08.2026")).toBeInTheDocument();

    vi.mocked(useAuth).mockReturnValue({
      user: { ...oldUser, last_mitvahim_date: "2026-08-15" }, refreshMe,
    } as ReturnType<typeof useAuth>);
    page.rerender(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ProfilePage /></QueryClientProvider>);

    expect(screen.getByText("15.08.2026")).toBeInTheDocument();
  });
});
