// frontend/src/components/ShiftDetailPanel.test.tsx
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ShiftDetailPanel from "./ShiftDetailPanel";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";
import * as assignmentsApi from "../api/assignments";
import * as shiftsApi from "../api/shifts";
import * as dutyConfigApi from "../api/dutyConfig";
import type { DutyShift } from "../api/shifts";
import type { CalendarShift, CalendarShiftAssignee } from "../api/calendar";
import type { DutyType } from "../api/dutyConfig";

const mockUseAuth = vi.fn(() => ({ user: null }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

const mockT = (key: string, options?: string | Record<string, string>) => {
  if (key === "weapon_ineligible.replace") return "החלף";
  if (typeof options === "string") return options;
  return options?.rangeType ? `${key} ${options.rangeType}` : key;
};
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mockT }),
}));

vi.mock("../api/swaps", () => ({
  listSwapsForAssignment: vi.fn(() => Promise.resolve([])),
  checkCoverEligibility: vi.fn(() => Promise.resolve({ eligible: true, reason: null })),
}));

vi.mock("../api/dutyConfig", () => ({
  listDutyTypes: vi.fn(() => Promise.resolve([])),
}));

vi.mock("../api/publicSettings", () => ({
  getPublicSettings: vi.fn(() => Promise.resolve({})),
}));

vi.mock("../api/assignments", () => ({
  listEffectiveDuties: vi.fn(() => Promise.resolve([])),
  getShiftCandidates: vi.fn(() => Promise.resolve([])),
}));

vi.mock("../api/shifts", () => ({
  removeShiftAssignment: vi.fn(() => Promise.resolve()),
  getShift: vi.fn(),
  assignBatch: vi.fn(() =>
    Promise.resolve({ primary_assignment_ids: [], reserve_assignment_ids: [], reserve_links_created: 0 })
  ),
}));

const WEAPON_REASON = "אין הכשרת נשק תקינה";

// What GET /shifts/{id} returns after the ineligible assignment was removed —
// a real ShiftOut whose reserve capacity the assign modal can read.
const freshDutyShift: DutyShift = {
  id: "shift-1",
  duty_type_id: "dt-1",
  duty_location_id: "loc-1",
  start_date: "2026-09-15",
  end_date: "2026-09-16",
  required_count: 1,
  notes: null,
  assigned_count: 0,
  reserve_assigned_count: 0,
  fill_status: "empty",
  status: "active",
  reserve_count_override: 2,
  calculated_reserve_count: 2,
  ineligible_count: 0,
};

function makeAssignee(overrides: Partial<CalendarShiftAssignee>): CalendarShiftAssignee {
  return {
    assignment_id: "a1",
    soldier_id: "s1",
    soldier_name: "Soldier One",
    hierarchy_label: null,
    is_reserve: false,
    profile_picture_url: null,
    dismissals: [],
    reserve_assignment_id: null,
    reserve_hierarchy_distance: null,
    called_up_from: null,
    called_up_to: null,
    primary_assignment_ids: [],
    hierarchy_path_ids: [],
    weapon_ineligible: false,
    weapon_ineligible_reason: null,
    range_eligibility: null,
    ...overrides,
  };
}

function makeShift(assignees: CalendarShiftAssignee[], overrides: Partial<CalendarShift> = {}): CalendarShift {
  return {
    id: "shift-1",
    duty_type_id: "dt-1",
    duty_type_name: "שמירה",
    duty_type_color: "#123456",
    duty_location_name: "שער ראשי",
    start_date: "2026-08-10",
    end_date: "2026-08-11",
    start_time: "08:00",
    end_time: "08:00",
    start_at: "2026-08-10T08:00:00Z",
    end_at: "2026-08-11T08:00:00Z",
    required_count: 2,
    assigned_count: 2,
    fill_status: "full",
    reserve_count: 1,
    required_range_type: "laser",
    assignees,
    ...overrides,
  };
}

function renderPanel(shift: CalendarShift) {
  const onRefreshNeeded = vi.fn();
  render(
    <SoldierModalProvider>
      <ShiftDetailPanel shift={shift} onClose={vi.fn()} onRefreshNeeded={onRefreshNeeded} />
    </SoldierModalProvider>
  );
  return { onRefreshNeeded };
}

// The name <button> rendered by SoldierLink sits directly inside the name
// group div, which holds the ⚠️ marker as its next sibling.
function nameRow(name: string): HTMLElement {
  return screen.getByText(name).parentElement as HTMLElement;
}

describe("ShiftDetailPanel weapon-ineligibility markers", () => {
  beforeEach(() => {
    vi.mocked(shiftsApi.removeShiftAssignment).mockClear();
    vi.mocked(shiftsApi.getShift).mockClear();
    vi.mocked(assignmentsApi.getShiftCandidates).mockClear();
  });

  it("shows a neutral state rather than a warning when only the legacy flag is present", () => {
    // Eligibility badges are gated to admins/commanders/duty managers (see the
    // "commander who is not a duty manager" and "plain soldier" tests below
    // for the gate itself) — use a privileged viewer here so this test can
    // focus on the neutral-state rendering.
    mockUseAuth.mockReturnValue({ user: { id: "mgr-1", role: "duty_manager", is_duty_manager: true } });
    renderPanel(
      makeShift([
        makeAssignee({
          assignment_id: "a-bad",
          soldier_id: "s-bad",
          soldier_name: "חייל לא כשיר",
          weapon_ineligible: true,
          weapon_ineligible_reason: WEAPON_REASON,
        }),
        makeAssignee({ assignment_id: "a-ok", soldier_id: "s-ok", soldier_name: "חייל כשיר" }),
      ])
    );

    expect(within(nameRow("חייל לא כשיר")).queryByLabelText("range_qualification.shiftDetail.warning")).toBeNull();
    expect(within(nameRow("חייל לא כשיר")).getByText("range_qualification.shiftDetail.unavailable")).toBeInTheDocument();
    // The eligible assignee on the same shift gets no marker either.
    expect(within(nameRow("חייל כשיר")).queryByLabelText("range_qualification.shiftDetail.warning")).toBeNull();
  });

  it("shows a neutral state for a reserve when only the legacy flag is present", () => {
    mockUseAuth.mockReturnValue({ user: { id: "mgr-1", role: "duty_manager", is_duty_manager: true } });
    renderPanel(
      makeShift([
        makeAssignee({
          assignment_id: "a-res",
          soldier_id: "s-res",
          soldier_name: "רזרב לא כשיר",
          is_reserve: true,
          weapon_ineligible: true,
          weapon_ineligible_reason: WEAPON_REASON,
        }),
      ])
    );

    expect(within(nameRow("רזרב לא כשיר")).queryByLabelText("range_qualification.shiftDetail.warning")).toBeNull();
    expect(within(nameRow("רזרב לא כשיר")).getByText("range_qualification.shiftDetail.unavailable")).toBeInTheDocument();
  });
  it("shows the required range and projection warning only for an uncovered assignee", () => {
    mockUseAuth.mockReturnValue({ user: { id: "mgr-1", role: "duty_manager", is_duty_manager: true } });
    renderPanel(
      makeShift([
        makeAssignee({
          soldier_name: "חייל ללא מטווח",
          range_eligibility: {
            eligible: false,
            required_range_type: "laser",
            qualification_source: null,
            covered_by_range_date: null,
            projected_valid_until: null,
            reason: "weapon_qualification",
            duty_type_name: "שמירה",
            start_date: "2026-08-10",
          },
        }),
        makeAssignee({
          assignment_id: "a-covered",
          soldier_id: "s-covered",
          soldier_name: "חייל עם מטווח",
          range_eligibility: {
            eligible: true,
            required_range_type: "laser",
            qualification_source: "planned_range",
            covered_by_range_date: "2026-08-08",
            projected_valid_until: "2027-08-08",
            reason: null,
            duty_type_name: "שמירה",
            start_date: "2026-08-10",
          },
        }),
      ])
    );

    expect(screen.getByText("מטווח לייזר")).toBeInTheDocument();
    const warningBadge = within(nameRow("חייל ללא מטווח")).getByLabelText("range_qualification.shiftDetail.warning");
    expect(warningBadge).toHaveAttribute(
      "title",
      expect.stringContaining("range_qualification.explanation.uncoveredDuty")
    );
    fireEvent.click(warningBadge);
    expect(screen.getByRole("tooltip")).toHaveClass("whitespace-pre-line");
    expect(within(nameRow("חייל עם מטווח")).queryByLabelText("range_qualification.shiftDetail.warning")).toBeNull();
  });

  it("shows a neutral state when a required-range eligibility fact is unavailable", () => {
    mockUseAuth.mockReturnValue({ user: { id: "mgr-1", role: "duty_manager", is_duty_manager: true } });
    renderPanel(makeShift([makeAssignee({ soldier_name: "חייל ללא נתון" })]));

    expect(screen.getByText("range_qualification.shiftDetail.unavailable")).toBeInTheDocument();
  });

  it("shows a blue info badge for an assignee covered only by a planned range", () => {
    mockUseAuth.mockReturnValue({ user: { id: "mgr-1", role: "duty_manager", is_duty_manager: true } });
    renderPanel(
      makeShift([
        makeAssignee({
          soldier_name: "חייל עם מטווח מתוכנן",
          range_eligibility: {
            eligible: true,
            required_range_type: "laser",
            qualification_source: "planned_range",
            covered_by_range_date: "2026-12-01",
            projected_valid_until: "2027-06-01",
            reason: null,
            duty_type_name: "שמירה",
            start_date: "2026-08-10",
          },
        }),
      ])
    );

    expect(screen.getByLabelText("range_qualification.shiftDetail.info")).toBeInTheDocument();
  });

  it("hides both the red and blue eligibility badges from a plain soldier", () => {
    mockUseAuth.mockReturnValue({ user: { id: "s1", role: "soldier", is_commander: false, is_duty_manager: false } });
    renderPanel(
      makeShift([
        makeAssignee({
          assignment_id: "a-bad",
          soldier_id: "s-bad",
          soldier_name: "חייל לא כשיר",
          range_eligibility: {
            eligible: false,
            required_range_type: "laser",
            qualification_source: null,
            covered_by_range_date: null,
            projected_valid_until: null,
            reason: "weapon_qualification",
            duty_type_name: "שמירה",
            start_date: "2026-08-10",
          },
        }),
        makeAssignee({
          assignment_id: "a-planned",
          soldier_id: "s-planned",
          soldier_name: "חייל עם מטווח מתוכנן",
          range_eligibility: {
            eligible: true,
            required_range_type: "laser",
            qualification_source: "planned_range",
            covered_by_range_date: "2026-12-01",
            projected_valid_until: "2027-06-01",
            reason: null,
            duty_type_name: "שמירה",
            start_date: "2026-08-10",
          },
        }),
      ])
    );

    expect(screen.queryByLabelText("range_qualification.shiftDetail.warning")).toBeNull();
    expect(screen.queryByLabelText("range_qualification.shiftDetail.info")).toBeNull();
  });

  it("shows the existing red badge to a commander who is not a duty manager", () => {
    mockUseAuth.mockReturnValue({ user: { id: "cmd-1", role: "commander", is_commander: true, is_duty_manager: false } });
    renderPanel(
      makeShift([
        makeAssignee({
          soldier_name: "חייל ללא מטווח",
          range_eligibility: {
            eligible: false,
            required_range_type: "laser",
            qualification_source: null,
            covered_by_range_date: null,
            projected_valid_until: null,
            reason: "weapon_qualification",
            duty_type_name: "שמירה",
            start_date: "2026-08-10",
          },
        }),
      ])
    );

    expect(screen.getByLabelText("range_qualification.shiftDetail.warning")).toBeInTheDocument();
  });
});

describe("ShiftDetailPanel duty requirements", () => {
  beforeEach(() => {
    vi.mocked(dutyConfigApi.listDutyTypes).mockReset().mockResolvedValue([]);
  });

  it("does not render the no-required-range copy for a duty without requirements", async () => {
    renderPanel(makeShift([], { required_range_type: null }));

    await waitFor(() => expect(dutyConfigApi.listDutyTypes).toHaveBeenCalled());
    expect(screen.queryByText("range_qualification.shiftDetail.noRequiredRange")).toBeNull();
  });

  it("shows both a laser range and military license requirement", async () => {
    const requirements: DutyType = {
      id: "dt-1",
      name: "שמירה",
      score_per_day: "1",
      description: null,
      active: true,
      requirements: { requires_military_driving_license: true },
      contact_name: null,
      contact_phone: null,
      start_time: null,
      end_time: null,
      instructions: null,
      is_external: false,
      required_range_type: "laser",
      eligible_node_ids: null,
    };
    vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([requirements]);

    renderPanel(makeShift([]));

    expect(await screen.findByText("מטווח לייזר")).toBeInTheDocument();
    expect(screen.getByText('נדרש רשנ"צ')).toBeInTheDocument();
  });
});

describe("ShiftDetailPanel Replace action", () => {
  beforeEach(() => {
    vi.mocked(shiftsApi.removeShiftAssignment).mockClear();
    vi.mocked(shiftsApi.getShift).mockReset().mockResolvedValue(freshDutyShift);
    vi.mocked(assignmentsApi.getShiftCandidates).mockClear();
  });

  it("shows a Replace button for a duty manager with a legacy ineligible flag", () => {
    mockUseAuth.mockReturnValue({ user: { id: "mgr-1", role: "duty_manager", is_duty_manager: true } });
    renderPanel(
      makeShift([
        makeAssignee({
          assignment_id: "a-bad",
          soldier_id: "s-bad",
          soldier_name: "חייל לא כשיר",
          weapon_ineligible: true,
          weapon_ineligible_reason: WEAPON_REASON,
        }),
      ])
    );

    // The Replace button lives in the row's right-aligned action group.
    expect(
      within(screen.getByText("חייל לא כשיר").closest("div.border") as HTMLElement).getByText("החלף")
    ).toBeInTheDocument();
  });

  it("shows a Replace button for an admin", () => {
    mockUseAuth.mockReturnValue({ user: { id: "adm-1", role: "admin", is_duty_manager: false } });
    renderPanel(
      makeShift([
        makeAssignee({
          assignment_id: "a-bad",
          soldier_id: "s-bad",
          soldier_name: "חייל לא כשיר",
          weapon_ineligible: true,
          weapon_ineligible_reason: WEAPON_REASON,
        }),
      ])
    );

    expect(screen.getByText("החלף")).toBeInTheDocument();
  });

  it("does not show a Replace button for a plain soldier", () => {
    mockUseAuth.mockReturnValue({ user: { id: "s1", role: "soldier", is_duty_manager: false } });
    renderPanel(
      makeShift([
        makeAssignee({
          assignment_id: "a-bad",
          soldier_id: "s-bad",
          soldier_name: "חייל לא כשיר",
          weapon_ineligible: true,
          weapon_ineligible_reason: WEAPON_REASON,
        }),
      ])
    );

    expect(screen.queryByText("החלף")).toBeNull();
  });

  it("clicking Replace removes the shift assignment, refreshes, and opens ShiftAssignModal with the refetched shift", async () => {
    mockUseAuth.mockReturnValue({ user: { id: "mgr-1", role: "duty_manager", is_duty_manager: true } });
    vi.mocked(assignmentsApi.getShiftCandidates).mockResolvedValue([
      {
        soldier_id: "s1",
        full_name: "מועמד חלופי",
        personal_number: "111",
        score_per_day: 0.5,
        blocked: false,
        blocked_reason: null,
        weapon_warning: false,
        hierarchy_path_ids: [],
      },
    ]);
    const { onRefreshNeeded } = renderPanel(
      makeShift([
        makeAssignee({
          assignment_id: "a-bad",
          soldier_id: "s-bad",
          soldier_name: "חייל לא כשיר",
          weapon_ineligible: true,
          weapon_ineligible_reason: WEAPON_REASON,
        }),
      ])
    );

    fireEvent.click(screen.getByText("החלף"));

    await waitFor(() =>
      expect(shiftsApi.removeShiftAssignment).toHaveBeenCalledWith("shift-1", "a-bad")
    );
    // The freed slot's shift is refetched so the modal opens with live
    // capacity (including reserve slots) rather than stale roster counts.
    expect(shiftsApi.getShift).toHaveBeenCalledWith("shift-1");
    expect(onRefreshNeeded).toHaveBeenCalled();
    // The modal renders the refetched shift's date…
    expect(await screen.findByText(/2026-09-15/)).toBeInTheDocument();
    // …its candidate table, and its reserve section, which only appears
    // when the refetched shift carries reserve capacity.
    expect(screen.getAllByText("מועמד חלופי").length).toBeGreaterThan(0);
    expect(screen.getByText("רזרביים")).toBeInTheDocument();
    expect(assignmentsApi.getShiftCandidates).toHaveBeenCalledWith("shift-1");
  });

  it("Replace also works for an ineligible reserve assignment", async () => {
    mockUseAuth.mockReturnValue({ user: { id: "mgr-1", role: "duty_manager", is_duty_manager: true } });
    renderPanel(
      makeShift([
        makeAssignee({
          assignment_id: "a-res",
          soldier_id: "s-res",
          soldier_name: "רזרב לא כשיר",
          is_reserve: true,
          weapon_ineligible: true,
          weapon_ineligible_reason: WEAPON_REASON,
        }),
      ])
    );

    fireEvent.click(screen.getByText("החלף"));

    await waitFor(() =>
      expect(shiftsApi.removeShiftAssignment).toHaveBeenCalledWith("shift-1", "a-res")
    );
    expect(shiftsApi.getShift).toHaveBeenCalledWith("shift-1");
    // The freed reserve assignment no longer holds a stale DutyReserveLink,
    // so a newly assigned reserve can attach to a primary again.
  });
 
  it("shows and executes Replace for an ineligible called-up reserve while preserving called-up presentation", async () => {
    mockUseAuth.mockReturnValue({ user: { id: "mgr-1", role: "duty_manager", is_duty_manager: true } });
    renderPanel(
      makeShift([
        makeAssignee({
          assignment_id: "a-called-up",
          soldier_id: "s-called-up",
          soldier_name: "רזרב נקרא",
          is_reserve: true,
          called_up_from: "2026-08-10",
          called_up_to: "2026-08-11",
          weapon_ineligible: true,
          weapon_ineligible_reason: WEAPON_REASON,
        }),
      ])
    );

    const row = screen.getByText("רזרב נקרא").closest("div.border") as HTMLElement;
    expect(within(row).getByText("reserve_called_up 2026-08-10–2026-08-11")).toBeInTheDocument();
    expect(within(row).getByText("החלף")).toBeInTheDocument();

    fireEvent.click(within(row).getByText("החלף"));

    await waitFor(() => {
      expect(shiftsApi.removeShiftAssignment).toHaveBeenCalledWith("shift-1", "a-called-up");
      expect(shiftsApi.getShift).toHaveBeenCalledWith("shift-1");
    });
  });
});
