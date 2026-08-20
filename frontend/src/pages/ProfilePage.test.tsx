import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ProfilePage from "./ProfilePage";
import { NotificationPref } from "../api/notifications";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../components/ExemptionsPanel", () => ({
  default: () => <div data-testid="exemptions-panel" />,
}));

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("../api/soldiers", () => ({
  listFieldUpdates: vi.fn(() => Promise.resolve([])),
  getRanks: vi.fn(() => Promise.resolve({ enlisted: [], officers: [], officer_academic: [] })),
  submitFieldUpdate: vi.fn(),
  // DeputiesPanel (rendered on ProfilePage for commanders/duty managers)
  // fetches the soldier list for its deputy picker.
  listSoldiers: vi.fn(() => Promise.resolve([])),
}));
vi.mock("../api/deputies", () => ({
  listDeputies: vi.fn(() => Promise.resolve([])),
  createDeputy: vi.fn(),
  revokeDeputy: vi.fn(),
}));
vi.mock("../api/auth", () => ({
  setEmail: vi.fn(),
}));
vi.mock("../api/registrationSettings", () => ({
  getRegistrationPublicSettings: vi.fn(() => Promise.resolve({})),
}));
vi.mock("../api/telegram", () => ({
  generateTelegramCode: vi.fn(),
  getTelegramStatus: vi.fn(() => Promise.resolve({ linked: false, telegram_username: null })),
  unlinkTelegram: vi.fn(),
}));
vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn(() => Promise.resolve([])),
}));
vi.mock("../api/rangeStatus", () => ({
  getSoldierRangeStatus: vi.fn(() => Promise.resolve({ statuses: [] })),
}));
vi.mock("../api/publicSettings", () => ({
  getPublicSettings: vi.fn(() => Promise.resolve({})),
}));

const mockGetPreferences = vi.fn();
vi.mock("../api/notifications", async () => {
  const actual = await vi.importActual<typeof import("../api/notifications")>("../api/notifications");
  return {
    ...actual,
    getPreferences: () => mockGetPreferences(),
    updatePreferences: vi.fn((prefs: unknown) => Promise.resolve(prefs)),
    listCommanderScopes: vi.fn(() => Promise.resolve([])),
    addCommanderScope: vi.fn(),
    removeCommanderScope: vi.fn(),
  };
});

const PREFS: NotificationPref[] = [
  { notification_type: "swap_offer", in_app_enabled: true, push_enabled: false, email_enabled: true },
  { notification_type: "algorithm_job_done", in_app_enabled: true, push_enabled: false, email_enabled: true },
];

function renderProfilePage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  mockGetPreferences.mockReset();
  mockGetPreferences.mockResolvedValue(PREFS);
});

describe("ProfilePage notification preferences", () => {
  it("hides manager-only notification types for a plain soldier", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "u1", full_name: "חייל", role: "soldier", is_commander: false, is_duty_manager: false },
    });

    renderProfilePage();

    expect(await screen.findByText("notifications.type_swap_offer")).toBeInTheDocument();
    expect(screen.queryByText("notifications.type_algorithm_job_done")).not.toBeInTheDocument();
  });

  it("shows manager-only notification types for a commander", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "u1", full_name: "מפקד", role: "commander", is_commander: true, is_duty_manager: false },
    });

    renderProfilePage();

    expect(await screen.findByText("notifications.type_swap_offer")).toBeInTheDocument();
    expect(await screen.findByText("notifications.type_algorithm_job_done")).toBeInTheDocument();
  });

  it("shows manager-only notification types for a duty manager", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "u1", full_name: "אחראי", role: "duty_manager", is_commander: false, is_duty_manager: true },
    });

    renderProfilePage();

    await waitFor(() => expect(screen.getByText("notifications.type_algorithm_job_done")).toBeInTheDocument());
  });
});
