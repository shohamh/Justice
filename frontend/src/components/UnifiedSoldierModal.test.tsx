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

const mockListSoldierConstraints = vi.fn().mockResolvedValue([]);
vi.mock("../api/constraints", () => ({
  listSoldierConstraints: (...args: unknown[]) => mockListSoldierConstraints(...args),
  approveConstraint: vi.fn(),
  rejectConstraint: vi.fn(),
  cancelConstraintForManager: vi.fn(),
}));
vi.mock("../api/rangeStatus", () => ({
  getSoldierRangeStatus: vi.fn().mockResolvedValue({ soldier_id: "s1", statuses: [] }),
}));
const mockGetSoldierDutyHistory = vi.fn().mockResolvedValue([]);
vi.mock("../api/dutyHistory", () => ({
  getSoldierDutyHistory: (...args: unknown[]) => mockGetSoldierDutyHistory(...args),
}));
vi.mock("../api/dutyConfig", () => ({
  listDutyTypes: vi.fn().mockResolvedValue([]),
}));
// Mocked t must be a stable module-level reference: react-i18next's real
// useTranslation returns a stable `t`, but an inline closure here would be a
// fresh function on every render, which (via DutyHistoryPanel's
// `load = useCallback(..., [soldierId, canManage, t])` and its
// `useEffect([isActive, soldierId, load])` that unconditionally calls
// setState) causes an infinite render loop the moment DutyHistoryPanel
// actually mounts. Mirrors DutyHistoryPanel.test.tsx's `mockT` pattern.
const mockT = (key: string) => (key === "errors.rank_track_incompatible" ? "הדרגה שנבחרה אינה תואמת למסלול השירות שנבחר" : key);
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mockT }),
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

describe("UnifiedSoldierModal profile editor field layout", () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
    mockUseAuth.mockReturnValue({ user: ADMIN_USER });
  });

  test("every profile field stacks in a plain single-column layout, not a CSS grid", async () => {
    // Regression test: this section previously used `grid grid-cols-1`
    // with two fields marked `col-span-2`. On real browsers the
    // `grid-cols-1` utility didn't win for this element (verified live via
    // devtools — computed grid-template-columns resolved to two implicit
    // tracks, driven by the col-span-2 children), scattering every field
    // across two columns and clipping/overlapping their labels and inputs
    // on mobile. jsdom doesn't run layout, so this can't assert pixel
    // positions — it asserts the fragile grid/col-span classes are gone
    // and the container uses plain block stacking instead.
    renderModal({}, true);
    fireEvent.click(screen.getByTestId("modal-tab-profile"));

    const genderLabel = await screen.findByText("soldier_profile.gender");
    const fieldsContainer = genderLabel.closest("label")?.parentElement;
    expect(fieldsContainer?.className).not.toMatch(/\bgrid\b/);
    expect(fieldsContainer?.className).toMatch(/\bspace-y-3\b/);
    expect(fieldsContainer?.querySelector(".col-span-2")).toBeNull();
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

    fireEvent.click(await screen.findByLabelText("נקה"));
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
    fireEvent.click(screen.getByLabelText("נקה"));
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

describe("UnifiedSoldierModal initialTab", () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
    mockUseAuth.mockReturnValue({ user: ADMIN_USER });
    mockGetSoldierDutyHistory.mockReset();
    mockGetSoldierDutyHistory.mockResolvedValue([]);
  });

  test("opens directly on the duty_history tab when initialTab is set", async () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <UnifiedSoldierModal
          soldier={soldier}
          score={null}
          nodes={[]}
          onClose={vi.fn()}
          onRefresh={vi.fn()}
          initialTab="duty_history"
        />
      </QueryClientProvider>,
    );

    const historyTabButton = screen.getByTestId("modal-tab-duty_history");
    expect(historyTabButton.className).toContain("border-indigo-600");
    // DutyHistoryPanel mounts and loads its (empty, mocked) history.
    expect(await screen.findByText("duty_history.empty")).toBeInTheDocument();
  });

  test("passes initialHistoryTypes through to DutyHistoryPanel so it seeds the event-type filter", async () => {
    // Regression lock: initialTab alone isn't enough — initialHistoryTypes
    // must also reach DutyHistoryPanel's `initialTypes` prop. Both fixture
    // events are dated in the past (relative to the mocked "today"), so
    // DutyHistoryPanel treats them as non-upcoming and never calls
    // listSwapsForAssignment/checkCoverEligibility, keeping this test free
    // of needing to mock ../api/swaps or ../api/assignments.
    mockGetSoldierDutyHistory.mockResolvedValue([
      {
        id: "a1", event_type: "assignment", date: "2026-01-10", end_date: "2026-01-11",
        title: "שמירה במוצב", description: null, status: "published",
        metadata: {}, created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "ra1", event_type: "range_assignment", date: "2026-01-10", end_date: null,
        title: "מטווח laser במטווח צפון", description: null, status: "present",
        metadata: { range_type: "laser", location_name: "מטווח צפון" }, created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <UnifiedSoldierModal
          soldier={soldier}
          score={null}
          nodes={[]}
          onClose={vi.fn()}
          onRefresh={vi.fn()}
          initialTab="duty_history"
          initialHistoryTypes={["assignment"]}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("history-event-assignment")).toBeInTheDocument();
    expect(screen.queryByTestId("history-event-range_assignment")).not.toBeInTheDocument();
  });
});

describe("UnifiedSoldierModal constraint cancellation", () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
    mockUseAuth.mockReturnValue({ user: ELIGIBLE_COMMANDER_USER });
    mockListSoldierConstraints.mockReset();
    mockListSoldierConstraints.mockResolvedValue([
      {
        id: "c1",
        soldier_id: "s1",
        constraint_type: "personal",
        start_date: "2026-01-01",
        end_date: "2026-12-31",
        status: "approved",
        reason: "test reason",
        can_cancel: true,
      },
    ]);
  });

  test("shows the extreme-action warning when cancelling an approved constraint", async () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <UnifiedSoldierModal
          soldier={soldier}
          score={null}
          nodes={[]}
          onClose={vi.fn()}
          onRefresh={vi.fn()}
        />
      </QueryClientProvider>,
    );

    // Click on constraints tab
    const constraintsTab = await screen.findByTestId("modal-tab-constraints");
    fireEvent.click(constraintsTab);

    // Find and click the cancel button for the constraint
    const cancelButton = await screen.findByTestId("cancel-constraint-c1");
    fireEvent.click(cancelButton);

    // Verify the warning is displayed with amber styling
    const warning = await screen.findByText((content, element) => {
      return element?.tagName.toLowerCase() === "p" && content.includes("team.cancel_constraint_active_warning");
    });
    expect(warning.className).toContain("amber");
  });
});
