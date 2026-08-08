// frontend/src/components/ShiftDetailPanel.test.tsx
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ShiftDetailPanel from "./ShiftDetailPanel";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";
import * as assignmentsApi from "../api/assignments";
import type { CalendarShift, CalendarShiftAssignee } from "../api/calendar";

const mockUseAuth = vi.fn(() => ({ user: null }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

const mockT = (key: string, fallback?: string) =>
  key === "weapon_ineligible.replace" ? "החלף" : (fallback ?? key);
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
  cancelAssignment: vi.fn(() => Promise.resolve({})),
  getShiftCandidates: vi.fn(() => Promise.resolve([])),
}));

vi.mock("../api/shifts", () => ({
  assignBatch: vi.fn(() =>
    Promise.resolve({ primary_assignment_ids: [], reserve_assignment_ids: [], reserve_links_created: 0 })
  ),
}));

const WEAPON_REASON = "אין הכשרת נשק תקינה";

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
    ...overrides,
  };
}

function makeShift(assignees: CalendarShiftAssignee[]): CalendarShift {
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
    assignees,
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
    vi.mocked(assignmentsApi.cancelAssignment).mockClear();
    vi.mocked(assignmentsApi.getShiftCandidates).mockClear();
  });

  it("shows a warning marker with the reason as title next to an ineligible primary", () => {
    mockUseAuth.mockReturnValue({ user: null });
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

    expect(within(nameRow("חייל לא כשיר")).getByTitle(WEAPON_REASON)).toHaveTextContent("⚠️");
    // The eligible assignee on the same shift gets no marker.
    expect(within(nameRow("חייל כשיר")).queryByTitle(WEAPON_REASON)).toBeNull();
    // Non-manager viewers see no Replace action.
    expect(screen.queryByText("החלף")).toBeNull();
  });

  it("shows the marker next to an ineligible reserve too", () => {
    mockUseAuth.mockReturnValue({ user: null });
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

    expect(within(nameRow("רזרב לא כשיר")).getByTitle(WEAPON_REASON)).toHaveTextContent("⚠️");
  });
});

describe("ShiftDetailPanel Replace action", () => {
  beforeEach(() => {
    vi.mocked(assignmentsApi.cancelAssignment).mockClear();
    vi.mocked(assignmentsApi.getShiftCandidates).mockClear();
  });

  it("shows a Replace button for a duty manager next to the ineligible marker", () => {
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

    expect(within(nameRow("חייל לא כשיר")).getByTitle(WEAPON_REASON)).toHaveTextContent("⚠️");
    // The Replace button lives in the row's right-aligned action group,
    // not inside the name group that holds the marker.
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

  it("clicking Replace cancels the assignment, refreshes, and opens ShiftAssignModal for the shift", async () => {
    mockUseAuth.mockReturnValue({ user: { id: "mgr-1", role: "duty_manager", is_duty_manager: true } });
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
      expect(assignmentsApi.cancelAssignment).toHaveBeenCalledWith("a-bad", "replacement")
    );
    expect(onRefreshNeeded).toHaveBeenCalled();
    expect(await screen.findByText("shifts.assign_modal_title")).toBeInTheDocument();
    // The modal opens targeted at this shift's freed slot.
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
      expect(assignmentsApi.cancelAssignment).toHaveBeenCalledWith("a-res", "replacement")
    );
  });
});