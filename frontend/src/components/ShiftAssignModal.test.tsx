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

  it("asks for confirmation before assigning a flagged candidate", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ShiftAssignModal shift={baseShift} dutyTypes={[]} onSaved={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => screen.getByText("לוחם לא כשיר"));
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByText(/^שבץ/));
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    confirmSpy.mockRestore();
  });
});
