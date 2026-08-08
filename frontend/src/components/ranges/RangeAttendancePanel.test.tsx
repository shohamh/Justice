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

  it("shows an error and re-enables submit if markRangeAttendance rejects", async () => {
    vi.mocked(rangesApi.markRangeAttendance).mockRejectedValue(new Error("network error"));
    render(<RangeAttendancePanel eventId="e1" assignments={[assignment]} onMarked={() => {}} />);

    fireEvent.click(screen.getByTestId("present-a1"));
    fireEvent.click(screen.getByTestId("submit-a1"));

    await waitFor(() => expect(screen.getByTestId("error-a1")).toBeInTheDocument());
    expect(screen.getByTestId("submit-a1")).not.toBeDisabled();
  });
});

describe("RangeAttendancePanel correction note requirement", () => {
  it("requires a note when correcting an already-present assignment to no_show", () => {
    render(
      <RangeAttendancePanel
        eventId="e1"
        assignments={[{
          id: "a1", soldier_id: "s1", is_reserve: false,
          attendance_status: "present", note: null,
        }]}
        onMarked={() => {}}
      />
    );
    fireEvent.click(screen.getByTestId("no-show-a1"));
    const submit = screen.getByTestId("submit-a1") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it("requires a note when correcting an already no_show assignment back to present", () => {
    render(
      <RangeAttendancePanel
        eventId="e2"
        assignments={[{
          id: "a2", soldier_id: "s2", is_reserve: false,
          attendance_status: "no_show", note: "לא הגיע",
        }]}
        onMarked={() => {}}
      />
    );
    fireEvent.click(screen.getByTestId("present-a2"));
    const submit = screen.getByTestId("submit-a2") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(screen.getByTestId("note-a2")).toBeTruthy();
  });

  it("does not require a note for a fresh pending-to-present mark", () => {
    render(
      <RangeAttendancePanel
        eventId="e3"
        assignments={[{
          id: "a3", soldier_id: "s3", is_reserve: false,
          attendance_status: "pending", note: null,
        }]}
        onMarked={() => {}}
      />
    );
    fireEvent.click(screen.getByTestId("present-a3"));
    const submit = screen.getByTestId("submit-a3") as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
  });
});
