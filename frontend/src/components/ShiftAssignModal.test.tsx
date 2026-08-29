import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import ShiftAssignModal from "./ShiftAssignModal";
import * as assignmentsApi from "../api/assignments";
import * as shiftsApi from "../api/shifts";
import type { DutyShift } from "../api/shifts";

vi.mock("../api/assignments");
vi.mock("../api/shifts");

const baseShift: DutyShift = {
  id: "shift-1", duty_type_id: "dt-1", duty_location_id: "loc-1",
  start_date: "2026-09-01", end_date: "2026-09-02",
  required_count: 1, notes: null, assigned_count: 0,
  reserve_assigned_count: 0, fill_status: "empty", status: "active",
  reserve_count_override: null, calculated_reserve_count: 0,
};

describe("ShiftAssignModal weapon eligibility warning", () => {
  beforeEach(() => {
    vi.mocked(assignmentsApi.getShiftCandidates).mockResolvedValue([
      {
        soldier_id: "s1", full_name: "לוחם לא כשיר", personal_number: "111",
        burden_share: 0.5, blocked: false, blocked_reason: null, weapon_warning: true,
        hierarchy_path_ids: [],
      },
    ]);
    vi.mocked(shiftsApi.assignBatch).mockResolvedValue({
      primary_assignment_ids: [], reserve_assignment_ids: [], reserve_links_created: 0,
    });
  });

  it("shows the candidate as selectable despite the warning", async () => {
    render(<ShiftAssignModal shift={baseShift} dutyTypes={[]} onSaved={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => screen.getByText("לוחם לא כשיר"));
    const checkbox = screen.getAllByRole("checkbox")[0] as HTMLInputElement;
    expect(checkbox.disabled).toBe(false);
  });

  it("uses a styled confirmation before assigning a flagged candidate", async () => {
    const nativeConfirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const onSaved = vi.fn();
    render(<ShiftAssignModal shift={baseShift} dutyTypes={[]} onSaved={onSaved} onClose={vi.fn()} />);
    await waitFor(() => screen.getByText("לוחם לא כשיר"));
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByText(/^שבץ/));
    expect(nativeConfirm).not.toHaveBeenCalled();
    expect(shiftsApi.assignBatch).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(shiftsApi.assignBatch).toHaveBeenCalled());
    expect(onSaved).toHaveBeenCalled();
    nativeConfirm.mockRestore();
  });
});

describe("ShiftAssignModal personal constraint override", () => {
  beforeEach(() => {
    vi.mocked(assignmentsApi.getShiftCandidates).mockResolvedValue([
      {
        soldier_id: "s1", full_name: "חייל אחד", personal_number: "1111111", burden_share: 0.2,
        blocked: false, blocked_reason: null, weapon_warning: false, hierarchy_path_ids: [],
        personal_constraint_warning: {
          reason: "בקשה אישית", start_date: "2026-09-01", end_date: "2026-09-05",
          decided_by: "רב\"ט כהן", decided_at: "2026-08-20T10:00:00Z",
        },
      },
    ]);
    vi.mocked(shiftsApi.assignBatch).mockResolvedValue({
      primary_assignment_ids: [], reserve_assignment_ids: [], reserve_links_created: 0,
    });
  });

  it("shows a warning icon for a constrained candidate and requires a reason before assigning them", async () => {
    render(<ShiftAssignModal shift={baseShift} dutyTypes={[]} onSaved={vi.fn()} onClose={vi.fn()} />);
    await screen.findByText("חייל אחד");

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByText(/שבץ/));

    expect(await screen.findByText(/נדרש נימוק/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "צורך מבצעי" } });
    fireEvent.click(screen.getByRole("button", { name: /אישור/ }));

    await waitFor(() => expect(shiftsApi.assignBatch).toHaveBeenCalledWith(
      baseShift.id, expect.objectContaining({ override_reason: "צורך מבצעי" }),
    ));
  });
});
