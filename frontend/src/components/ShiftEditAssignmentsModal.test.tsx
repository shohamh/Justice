import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ShiftEditAssignmentsModal from "./ShiftEditAssignmentsModal";
import * as assignmentsApi from "../api/assignments";
import * as calendarApi from "../api/calendar";
import type { DutyShift } from "../api/shifts";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../api/assignments", () => ({ getShiftCandidates: vi.fn() }));
vi.mock("../api/calendar", () => ({ getCalendarShift: vi.fn() }));
vi.mock("../api/shifts", () => ({ assignBatch: vi.fn(), removeShiftAssignment: vi.fn() }));

const shift: DutyShift = {
  id: "shift-1",
  duty_type_id: "duty-type-1",
  duty_location_id: "location-1",
  start_date: "2026-09-10",
  end_date: "2026-09-11",
  required_count: 1,
  notes: null,
  assigned_count: 2,
  reserve_assigned_count: 1,
  fill_status: "full",
  status: "active",
  ineligible_count: 0,
  reserve_count_override: 1,
};

beforeEach(() => {
  vi.mocked(assignmentsApi.getShiftCandidates).mockResolvedValue([
    {
      soldier_id: "soldier-candidate",
      full_name: "Candidate Soldier",
      personal_number: "12345678",
      burden_share: 0.25,
      blocked: false,
      blocked_reason: null,
      blocked_detail: null,
      weapon_warning: false,
      hierarchy_path_ids: [],
      personal_constraint_warning: null,
    },
  ]);
  vi.mocked(calendarApi.getCalendarShift).mockResolvedValue({
    assignees: [
      {
        assignment_id: "primary-1",
        soldier_id: "soldier-primary",
        soldier_name: "Primary Soldier",
        is_reserve: false,
        dismissals: [],
        reserve_assignment_id: "reserve-1",
        primary_assignment_ids: [],
        hierarchy_path_ids: [],
      },
      {
        assignment_id: "reserve-1",
        soldier_id: "soldier-reserve",
        soldier_name: "Reserve Soldier",
        is_reserve: true,
        dismissals: [],
        reserve_assignment_id: null,
        primary_assignment_ids: ["primary-1"],
        hierarchy_path_ids: [],
      },
    ],
  } as Awaited<ReturnType<typeof calendarApi.getCalendarShift>>);
});

describe("ShiftEditAssignmentsModal", () => {
  it("exposes manual primary, reserve, and saved assignment row boundaries", async () => {
    render(
      <ShiftEditAssignmentsModal
        shift={shift}
        dutyTypes={[{ id: "duty-type-1", name: "Duty", eligible_node_ids: [] }]}
        onSaved={vi.fn()}
        onClose={vi.fn()}
      />
    );

    expect(await screen.findByTestId("manual-assignment-modal-shift-1")).toBeVisible();
    expect(screen.getByTestId("manual-add-primary")).toBeEnabled();
    expect(screen.getByTestId("manual-add-reserve")).toBeEnabled();
    expect(screen.getByTestId("manual-primary-candidate-soldier-candidate")).toBeVisible();
    expect(screen.getByTestId("manual-reserve-candidate-soldier-candidate")).toBeVisible();
    expect(screen.getByTestId("assignment-primary-primary-1")).toBeVisible();
    expect(screen.getByTestId("assignment-reserve-reserve-1")).toBeVisible();
    expect(screen.getByTestId("manual-assignment-save")).toBeDisabled();
  });
});
