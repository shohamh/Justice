import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ShiftEditAssignmentsModal from "./ShiftEditAssignmentsModal";
import * as assignmentsApi from "../api/assignments";
import * as calendarApi from "../api/calendar";
import * as shiftsApi from "../api/shifts";
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
  vi.clearAllMocks();
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

  it("selects a primary candidate, saves it, and keeps the pending assignment visible", async () => {
    vi.mocked(calendarApi.getCalendarShift).mockResolvedValue({
      assignees: [],
    } as Awaited<ReturnType<typeof calendarApi.getCalendarShift>>);
    vi.mocked(shiftsApi.assignBatch).mockResolvedValue({
      primary_assignment_ids: ["created-primary-1"],
      reserve_assignment_ids: [],
      reserve_links_created: 0,
    });
    const onSaved = vi.fn();

    render(
      <ShiftEditAssignmentsModal
        shift={{ ...shift, assigned_count: 0, reserve_assigned_count: 0 }}
        dutyTypes={[{ id: "duty-type-1", name: "Duty", eligible_node_ids: [] }]}
        onSaved={onSaved}
        onClose={vi.fn()}
      />
    );

    fireEvent.click(await screen.findByTestId("manual-primary-candidate-soldier-candidate"));
    expect(screen.getByTestId("assignment-primary-pending-soldier-candidate")).toBeVisible();
    fireEvent.click(screen.getByTestId("manual-assignment-save"));

    await waitFor(() => expect(shiftsApi.assignBatch).toHaveBeenCalledWith("shift-1", {
      primaries: ["soldier-candidate"],
      reserves: [],
    }));
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("assignment-primary-pending-soldier-candidate")).toBeVisible();
  });
});

describe("ShiftEditAssignmentsModal personal constraint override", () => {
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
        personal_constraint_warning: {
          reason: "בקשה אישית",
          start_date: "2026-09-01",
          end_date: "2026-09-05",
          decided_by: "רב\"ט כהן",
          decided_at: "2026-08-20T10:00:00Z",
        },
      },
    ]);
    vi.mocked(calendarApi.getCalendarShift).mockResolvedValue({
      assignees: [],
    } as Awaited<ReturnType<typeof calendarApi.getCalendarShift>>);
    vi.mocked(shiftsApi.assignBatch).mockResolvedValue({
      primary_assignment_ids: ["created-primary-1"],
      reserve_assignment_ids: [],
      reserve_links_created: 0,
    });
  });

  it("shows a constraint-warning indicator for a candidate with an approved personal constraint", async () => {
    render(
      <ShiftEditAssignmentsModal
        shift={{ ...shift, assigned_count: 0, reserve_assigned_count: 0 }}
        dutyTypes={[{ id: "duty-type-1", name: "Duty", eligible_node_ids: [] }]}
        onSaved={vi.fn()}
        onClose={vi.fn()}
      />
    );

    const row = await screen.findByTestId("manual-primary-candidate-soldier-candidate");
    expect(row.querySelector("button[title*='אילוץ אישי מאושר']")).toBeVisible();
  });

  it("opens the override-reason modal when saving with a constrained candidate selected, and completes the assignment once a reason is confirmed", async () => {
    render(
      <ShiftEditAssignmentsModal
        shift={{ ...shift, assigned_count: 0, reserve_assigned_count: 0 }}
        dutyTypes={[{ id: "duty-type-1", name: "Duty", eligible_node_ids: [] }]}
        onSaved={vi.fn()}
        onClose={vi.fn()}
      />
    );

    fireEvent.click(await screen.findByTestId("manual-primary-candidate-soldier-candidate"));
    fireEvent.click(screen.getByTestId("manual-assignment-save"));

    expect(await screen.findByText(/נדרש נימוק/)).toBeInTheDocument();
    expect(shiftsApi.assignBatch).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText("נימוק העקיפה..."), { target: { value: "צורך מבצעי" } });
    fireEvent.click(screen.getByRole("button", { name: /אישור/ }));

    await waitFor(() => expect(shiftsApi.assignBatch).toHaveBeenCalledWith("shift-1", {
      primaries: ["soldier-candidate"],
      reserves: [],
      override_reason: "צורך מבצעי",
    }));
  });

  it("excludes a constrained candidate from auto-select", async () => {
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
        personal_constraint_warning: {
          reason: "בקשה אישית", start_date: "2026-09-01", end_date: "2026-09-05",
          decided_by: "רב\"ט כהן", decided_at: "2026-08-20T10:00:00Z",
        },
      },
      {
        soldier_id: "soldier-clean",
        full_name: "Clean Soldier",
        personal_number: "87654321",
        burden_share: 0.5,
        blocked: false,
        blocked_reason: null,
        blocked_detail: null,
        weapon_warning: false,
        hierarchy_path_ids: [],
        personal_constraint_warning: null,
      },
    ]);

    render(
      <ShiftEditAssignmentsModal
        shift={{ ...shift, assigned_count: 0, reserve_assigned_count: 0, required_count: 2 }}
        dutyTypes={[{ id: "duty-type-1", name: "Duty", eligible_node_ids: [] }]}
        onSaved={vi.fn()}
        onClose={vi.fn()}
      />
    );

    await screen.findByTestId("manual-primary-candidate-soldier-candidate");
    const autoSelectButtons = screen.getAllByText("בחר אוטומטית");
    fireEvent.click(autoSelectButtons[0]);

    expect(screen.getByTestId("assignment-primary-pending-soldier-clean")).toBeVisible();
    expect(screen.queryByTestId("assignment-primary-pending-soldier-candidate")).not.toBeInTheDocument();
  });
});
