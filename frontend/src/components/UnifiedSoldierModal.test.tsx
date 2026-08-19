import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, test, vi, beforeEach } from "vitest";
import UnifiedSoldierModal from "./UnifiedSoldierModal";
import type { SoldierDTO } from "../api/soldiers";

const mockUpdateSoldierProfile = vi.fn();
const mockGetRanks = vi.fn().mockResolvedValue({ enlisted: ["טוראי"], officers: ["רסן"], officer_academic: ["סרן"] });
vi.mock("../api/soldiers", () => ({
  updateSoldier: vi.fn(),
  updateSoldierProfile: (...args: unknown[]) => mockUpdateSoldierProfile(...args),
  getRanks: (...args: unknown[]) => mockGetRanks(...args),
}));
vi.mock("../api/constraints", () => ({
  listSoldierConstraints: vi.fn().mockResolvedValue([]),
  approveConstraint: vi.fn(),
  rejectConstraint: vi.fn(),
}));
vi.mock("../api/rangeStatus", () => ({
  getSoldierRangeStatus: vi.fn().mockResolvedValue({ soldier_id: "s1", statuses: [] }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => (key === "errors.rank_track_incompatible" ? "הדרגה שנבחרה אינה תואמת למסלול השירות שנבחר" : key),
  }),
}));
const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

const ADMIN_USER = { personal_number: "admin1", role: "admin", is_duty_manager: false, is_commander: false };
const ELIGIBLE_COMMANDER_USER = { personal_number: "cmdr1", role: "soldier", is_duty_manager: false, is_commander: true };
const INELIGIBLE_COMMANDER_USER = { personal_number: "cmdr2", role: "soldier", is_duty_manager: false, is_commander: true };

const soldier: SoldierDTO = {
  id: "s1",
  personal_number: "1234567",
  full_name: "Test Soldier",
  role: "soldier",
  hierarchy_node_id: null,
  phone: "0500000000",
  must_change_password: false,
  left_at: null,
  enrolled_at: null,
  gender: null,
  is_officer: false,
  is_career: false,
  rank: null,
  rank_track: null,
  bahad1_graduate: false,
  has_military_driving_license: false,
  military_driving_license_expiry: null,
  enlistment_date: null,
  mandatory_end_date: null,
  discharge_date: null,
  last_mitvahim_date: null,
  last_alal_date: null,
  telegram_linked: false,
  next_rank_date: null,
  next_rank_date_overridden: false,
  can_edit_rank_advancement: false,
};

function renderModal(soldierOverrides: Partial<SoldierDTO> = {}, initialEditing = false) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <UnifiedSoldierModal
        soldier={{ ...soldier, ...soldierOverrides }}
        score={null}
        nodes={[]}
        onClose={vi.fn()}
        onRefresh={vi.fn()}
        initialEditing={initialEditing}
      />
    </QueryClientProvider>,
  );
}

describe("UnifiedSoldierModal profile save error handling", () => {
  beforeEach(() => {
    mockUpdateSoldierProfile.mockReset();
    mockUseAuth.mockReset();
    mockUseAuth.mockReturnValue({ user: ADMIN_USER });
  });

  test("a rejected profile save surfaces a translated error and re-enables the save button", async () => {
    mockUpdateSoldierProfile.mockRejectedValueOnce({
      response: { data: { detail: "rank_track_incompatible: rank 'סרן' is not compatible with track 'חובה'" } },
    });
    renderModal({}, true);

    fireEvent.click(screen.getByTestId("modal-tab-profile"));
    // The save button is a no-op (and disabled) when nothing changed — this
    // test exercises the rejection path, so it must actually dirty a field.
    fireEvent.change(screen.getByLabelText("soldier_profile.gender"), { target: { value: "male" } });
    fireEvent.click(screen.getByText("duty_config.save"));

    expect(await screen.findByText("הדרגה שנבחרה אינה תואמת למסלול השירות שנבחר")).toBeInTheDocument();
    // Button must not be stuck disabled/saving forever.
    await waitFor(() => expect(screen.getByText("duty_config.save")).not.toBeDisabled());
  });
});

describe("UnifiedSoldierModal scoped rank/next-rank-date correction", () => {
  beforeEach(() => {
    mockUpdateSoldierProfile.mockReset();
    mockUseAuth.mockReset();
  });

  test("the profile view shows the next-rank date with an automatic indication", async () => {
    mockUseAuth.mockReturnValue({ user: ADMIN_USER });
    renderModal({ next_rank_date: "2027-01-15", next_rank_date_overridden: false });

    fireEvent.click(screen.getByTestId("modal-tab-profile"));

    expect(await screen.findByText("soldier_profile.next_rank_date_automatic")).toBeInTheDocument();
  });

  test("the profile view shows the next-rank date with a manual indication when overridden", async () => {
    mockUseAuth.mockReturnValue({ user: ADMIN_USER });
    renderModal({ next_rank_date: "2027-01-15", next_rank_date_overridden: true });

    fireEvent.click(screen.getByTestId("modal-tab-profile"));

    expect(await screen.findByText("soldier_profile.next_rank_date_manual")).toBeInTheDocument();
  });

  test("an eligible commander without ordinary edit authority sees only the narrow rank/date editor", async () => {
    mockUseAuth.mockReturnValue({ user: ELIGIBLE_COMMANDER_USER });
    renderModal({ can_edit_rank_advancement: true, rank: "טוראי", rank_track: "enlisted" });

    // No full-profile edit pencil for this user.
    expect(screen.queryByTestId("modal-edit-toggle")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("modal-tab-profile"));

    expect(screen.getByTestId("rank-correction-toggle")).toBeInTheDocument();
  });

  test("submitting the narrow rank/date editor calls updateSoldierProfile with only rank/track/date fields", async () => {
    mockUseAuth.mockReturnValue({ user: ELIGIBLE_COMMANDER_USER });
    mockUpdateSoldierProfile.mockResolvedValueOnce({ ...soldier, can_edit_rank_advancement: true });
    renderModal({ can_edit_rank_advancement: true, rank: "טוראי", rank_track: "enlisted", next_rank_date: "2027-01-15" });

    fireEvent.click(screen.getByTestId("modal-tab-profile"));
    fireEvent.click(screen.getByTestId("rank-correction-toggle"));

    const dateInput = await screen.findByTestId("next-rank-date-input");
    fireEvent.change(dateInput, { target: { value: "30/06/2027" } });
    fireEvent.click(screen.getByTestId("rank-correction-submit"));

    await waitFor(() => expect(mockUpdateSoldierProfile).toHaveBeenCalledTimes(1));
    expect(mockUpdateSoldierProfile).toHaveBeenCalledWith("s1", {
      rank: "טוראי",
      rank_track: "enlisted",
      is_officer: false,
      next_rank_date: "2027-06-30",
    });
  });

  test("clearing the next-rank date in the narrow editor sends an explicit null", async () => {
    mockUseAuth.mockReturnValue({ user: ELIGIBLE_COMMANDER_USER });
    mockUpdateSoldierProfile.mockResolvedValueOnce({ ...soldier, can_edit_rank_advancement: true });
    renderModal({ can_edit_rank_advancement: true, rank: "טוראי", rank_track: "enlisted", next_rank_date: "2027-01-15" });

    fireEvent.click(screen.getByTestId("modal-tab-profile"));
    fireEvent.click(screen.getByTestId("rank-correction-toggle"));

    fireEvent.click(await screen.findByText("soldier_profile.clear"));
    fireEvent.click(screen.getByTestId("rank-correction-submit"));

    await waitFor(() => expect(mockUpdateSoldierProfile).toHaveBeenCalledTimes(1));
    expect(mockUpdateSoldierProfile).toHaveBeenCalledWith("s1", {
      rank: "טוראי",
      rank_track: "enlisted",
      is_officer: false,
      next_rank_date: null,
    });
  });

  test("an ineligible commander has no rank/date edit control", async () => {
    mockUseAuth.mockReturnValue({ user: INELIGIBLE_COMMANDER_USER });
    renderModal({ can_edit_rank_advancement: false, rank: "טוראי", rank_track: "enlisted" });

    expect(screen.queryByTestId("modal-edit-toggle")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("modal-tab-profile"));

    expect(screen.queryByTestId("rank-correction-toggle")).not.toBeInTheDocument();
  });
});

describe("UnifiedSoldierModal full editor rank-field dirty gating and next-rank-date", () => {
  beforeEach(() => {
    mockUpdateSoldierProfile.mockReset();
    mockUseAuth.mockReset();
    mockUseAuth.mockReturnValue({ user: ADMIN_USER });
  });

  test("an ordinary full-editor save omits unchanged rank/rank_track/next_rank_date fields", async () => {
    // Finding 1's second line of defense: an admin editing an unrelated field
    // (gender) must not have the unchanged rank fields included in the
    // request body, even though can_edit_rank_advancement is true.
    mockUpdateSoldierProfile.mockResolvedValueOnce({
      ...soldier, can_edit_rank_advancement: true, rank: "טוראי", rank_track: "enlisted", next_rank_date: "2027-01-15",
    });
    const { container } = renderModal(
      { can_edit_rank_advancement: true, rank: "טוראי", rank_track: "enlisted", next_rank_date: "2027-01-15" },
      true,
    );

    fireEvent.click(screen.getByTestId("modal-tab-profile"));
    const genderSelect = container.querySelector("select") as HTMLSelectElement;
    fireEvent.change(genderSelect, { target: { value: "male" } });
    fireEvent.click(screen.getByText("duty_config.save"));

    await waitFor(() => expect(mockUpdateSoldierProfile).toHaveBeenCalledTimes(1));
    const payload = mockUpdateSoldierProfile.mock.calls[0][1];
    expect(payload).not.toHaveProperty("rank");
    expect(payload).not.toHaveProperty("rank_track");
    expect(payload).not.toHaveProperty("is_officer");
    expect(payload).not.toHaveProperty("next_rank_date");
  });

  test("the full editor shows a next-rank-date field for an authorized actor and clearing it sends explicit null", async () => {
    mockUpdateSoldierProfile.mockResolvedValueOnce({
      ...soldier, can_edit_rank_advancement: true, rank: "טוראי", rank_track: "enlisted",
    });
    renderModal(
      { can_edit_rank_advancement: true, rank: "טוראי", rank_track: "enlisted", next_rank_date: "2027-01-15" },
      true,
    );

    fireEvent.click(screen.getByTestId("modal-tab-profile"));
    const dateInput = await screen.findByTestId("next-rank-date-input");
    fireEvent.click(screen.getByText("soldier_profile.clear"));
    fireEvent.click(screen.getByText("duty_config.save"));

    await waitFor(() => expect(mockUpdateSoldierProfile).toHaveBeenCalledTimes(1));
    const payload = mockUpdateSoldierProfile.mock.calls[0][1];
    expect(payload).toHaveProperty("next_rank_date", null);
    expect(dateInput).toBeInTheDocument();
  });

  test("the full editor's next-rank-date field is absent for an actor without rank-advancement authority", async () => {
    renderModal({ can_edit_rank_advancement: false, next_rank_date: "2027-01-15" }, true);

    fireEvent.click(screen.getByTestId("modal-tab-profile"));

    expect(screen.queryByTestId("next-rank-date-input")).not.toBeInTheDocument();
  });
});

describe("UnifiedSoldierModal duty-history tab visibility for a commander", () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
  });

  test("a commander (not admin/DM) still sees the duty_history tab for a soldier outside their direct-report list", async () => {
    // Regression lock for item 16: the tab must render for any commander,
    // not just admins/duty-managers — this soldier is not the commander's
    // direct report, only somewhere in their commanded subtree, which is
    // exactly the scenario the backend's can_view_soldier_scope already
    // covers (see backend/app/services/tests/test_authority.py and
    // backend/tests/integration/test_soldiers_api.py). The frontend TABS
    // list must not additionally gate this.
    mockUseAuth.mockReturnValue({
      user: { personal_number: "cmdr-scope-1", role: "soldier", is_duty_manager: false, is_commander: true },
    });
    renderModal({ personal_number: "9999999" });

    expect(await screen.findByTestId("modal-tab-duty_history")).toBeInTheDocument();
  });
});
