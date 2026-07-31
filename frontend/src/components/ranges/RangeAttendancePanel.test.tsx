import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import RangeAttendancePanel from "./RangeAttendancePanel";
import * as rangesApi from "../../api/ranges";

vi.mock("../../api/ranges");

const assignment = {
  id: "a1", soldier_id: "s1", is_reserve: false,
  attendance_status: "pending" as const, note: null,
};

describe("RangeAttendancePanel", () => {
  it("requires a note before submitting a no-show", () => {
    render(<RangeAttendancePanel eventId="e1" assignments={[assignment]} onMarked={() => {}} />);

    fireEvent.click(screen.getByTestId("no-show-a1"));
    const submitButton = screen.getByTestId("submit-a1");
    expect(submitButton).toBeDisabled();
  });

  it("calls markRangeAttendance with present and no note required", async () => {
    vi.mocked(rangesApi.markRangeAttendance).mockResolvedValue({ ...assignment, attendance_status: "present" });
    const onMarked = vi.fn();
    render(<RangeAttendancePanel eventId="e1" assignments={[assignment]} onMarked={onMarked} />);

    fireEvent.click(screen.getByTestId("present-a1"));
    fireEvent.click(screen.getByTestId("submit-a1"));

    await waitFor(() => expect(rangesApi.markRangeAttendance).toHaveBeenCalledWith("e1", "a1", "present", undefined));
    await waitFor(() => expect(onMarked).toHaveBeenCalled());
  });
});
