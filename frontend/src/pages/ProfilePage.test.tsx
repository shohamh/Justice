import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ProfilePage from "./ProfilePage";
import { NotificationPref } from "../api/notifications";
import { listFieldUpdates } from "../api/soldiers";

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
      refreshMe: vi.fn().mockResolvedValue(undefined),
    });

    renderProfilePage();

    expect(await screen.findByText("notifications.type_swap_offer")).toBeInTheDocument();
    expect(screen.queryByText("notifications.type_algorithm_job_done")).not.toBeInTheDocument();
  });

  it("shows manager-only notification types for a commander", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "u1", full_name: "מפקד", role: "commander", is_commander: true, is_duty_manager: false },
      refreshMe: vi.fn().mockResolvedValue(undefined),
    });

    renderProfilePage();

    expect(await screen.findByText("notifications.type_swap_offer")).toBeInTheDocument();
    expect(await screen.findByText("notifications.type_algorithm_job_done")).toBeInTheDocument();
  });

  it("shows manager-only notification types for a duty manager", async () => {
    mockUseAuth.mockReturnValue({
      user: { id: "u1", full_name: "אחראי", role: "duty_manager", is_commander: false, is_duty_manager: true },
      refreshMe: vi.fn().mockResolvedValue(undefined),
    });

    renderProfilePage();

    await waitFor(() => expect(screen.getByText("notifications.type_algorithm_job_done")).toBeInTheDocument());
  });
});


describe("ProfilePage unified service-details form", () => {
  it("displays the unit join date from the authenticated profile", async () => {
    mockUseAuth.mockReturnValue({
      user: {
        id: "u1", full_name: "חייל", role: "soldier", is_commander: false,
        is_duty_manager: false, email: null, email_verified: false,
        gender: null, rank: null, rank_track: null, phone: null,
        unit_join_date: "2026-01-15", last_mitvahim_date: null, last_alal_date: null,
        mandatory_end_date: null, discharge_date: null,
        has_military_driving_license: false, military_driving_license_expiry: null,
      },
      refreshMe: vi.fn().mockResolvedValue(undefined),
    });
    renderProfilePage();

    expect(await screen.findByText(/soldier_profile\.unit_join_date/)).toBeInTheDocument();
    expect(screen.getByText("15.01.2026")).toBeInTheDocument();
  });

  it("seeds controls with the current value and disables submit while unchanged", async () => {
    mockUseAuth.mockReturnValue({
      user: {
        id: "u1", full_name: "חייל", role: "soldier", is_commander: false,
        is_duty_manager: false, email: null, email_verified: false,
        gender: "male", rank: null, rank_track: null, phone: null,
        last_mitvahim_date: null, last_alal_date: null,
        mandatory_end_date: null, discharge_date: null,
        has_military_driving_license: false, military_driving_license_expiry: null,
      },
      refreshMe: vi.fn().mockResolvedValue(undefined),
    });
    renderProfilePage();

    // RTL's ByDisplayValue doesn't match <select>; assert the control value
    // directly once the seeding effect has run.
    const genderSelect = () =>
      screen.getAllByRole("combobox").filter((el) => el.tagName === "SELECT")[0] as HTMLSelectElement;
    await waitFor(() => expect(genderSelect().value).toBe("male"));
    const submitButtons = screen.getAllByRole("button", { name: "soldier_profile.submit_update" });
    // First submit button belongs to the gender row.
    expect(submitButtons[0]).toBeDisabled();

    fireEvent.change(genderSelect(), { target: { value: "female" } });
    expect(submitButtons[0]).toBeEnabled();
  });

  it("shows the pending field-update value as effective and disables same-value submit", async () => {
    vi.mocked(listFieldUpdates).mockResolvedValue([
      {
        id: "fu1", soldier_id: "u1", soldier_name: "חייל", node_name: null,
        field_name: "phone", previous_value: null, new_value: "052-2222222",
        status: "pending", decided_by: null, decided_at: null, decision_note: null,
        created_at: "2026-08-24T00:00:00Z", nearest_commander: null,
        nearest_duty_manager: null, can_approve: false,
      },
    ]);
    mockUseAuth.mockReturnValue({
      user: {
        id: "u1", full_name: "חייל", role: "soldier", is_commander: false,
        is_duty_manager: false, email: null, email_verified: false,
        gender: null, rank: null, rank_track: null, phone: "050-1111111",
        last_mitvahim_date: null, last_alal_date: null,
        mandatory_end_date: null, discharge_date: null,
        has_military_driving_license: false, military_driving_license_expiry: null,
      },
      refreshMe: vi.fn().mockResolvedValue(undefined),
    });
    renderProfilePage();

    const phoneInput = await screen.findByDisplayValue("052-2222222");
    const submitButtons = screen.getAllByRole("button", { name: "soldier_profile.submit_update" });
    // Third submit button belongs to the phone row (gender, rank, phone).
    await waitFor(() => expect(submitButtons[2]).toBeDisabled());

    fireEvent.change(phoneInput, { target: { value: "050-1234567" } });
    await waitFor(() => expect(submitButtons[2]).toBeEnabled());
  });

  it("reveals the food-constraints explanation when its help icon is clicked", async () => {
    mockUseAuth.mockReturnValue({
      user: {
        id: "u1", full_name: "חייל", role: "soldier", is_commander: false,
        is_duty_manager: false, email: null, email_verified: false,
        gender: null, rank: null, rank_track: null, phone: null,
        last_mitvahim_date: null, last_alal_date: null,
        mandatory_end_date: null, discharge_date: null,
        has_military_driving_license: false, military_driving_license_expiry: null,
      },
      refreshMe: vi.fn().mockResolvedValue(undefined),
    });
    renderProfilePage();

    await screen.findByTestId("food-constraints-input");
    expect(screen.queryByText("soldier_profile.food_constraints_help")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("food-constraints-help-toggle"));
    expect(screen.getByText("soldier_profile.food_constraints_help")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("food-constraints-help-toggle"));
    expect(screen.queryByText("soldier_profile.food_constraints_help")).not.toBeInTheDocument();
  });
});

describe("ProfilePage profile refresh", () => {
  it("refreshes the authenticated profile on mount and reflects the approved date", async () => {
    const refreshMe = vi.fn().mockResolvedValue(undefined);
    mockUseAuth.mockReturnValue({
      user: {
        id: "u1", full_name: "חייל", role: "soldier", is_commander: false,
        is_duty_manager: false, email: null, email_verified: false,
        gender: "male", rank: null, rank_track: null, phone: null,
        last_mitvahim_date: "2026-08-01", last_alal_date: null,
        mandatory_end_date: null, discharge_date: null,
        has_military_driving_license: false, military_driving_license_expiry: null,
      },
      refreshMe,
    });

    renderProfilePage();

    await waitFor(() => expect(refreshMe).toHaveBeenCalledTimes(1));
    expect(await screen.findByDisplayValue("01/08/2026")).toBeInTheDocument();

    mockUseAuth.mockReturnValue({
      user: {
        id: "u1", full_name: "חייל", role: "soldier", is_commander: false,
        is_duty_manager: false, email: null, email_verified: false,
        gender: "male", rank: null, rank_track: null, phone: null,
        last_mitvahim_date: "2026-08-15", last_alal_date: null,
        mandatory_end_date: null, discharge_date: null,
        has_military_driving_license: false, military_driving_license_expiry: null,
      },
      refreshMe,
    });
    renderProfilePage();

    expect(await screen.findByDisplayValue("15/08/2026")).toBeInTheDocument();
  });
});
