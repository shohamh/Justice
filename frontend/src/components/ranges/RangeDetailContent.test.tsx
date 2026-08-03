import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import RangeDetailContent from "./RangeDetailContent";
import { RangeEvent } from "../../api/ranges";

vi.mock("../planning", () => ({
  RosterSection: ({ assignments, assignmentActionRenderer }: { assignments: Array<{ id: string }>; assignmentActionRenderer: (assignment: { id: string }) => React.ReactNode }) => <div>{assignments.map(assignment => <div key={assignment.id}>{assignmentActionRenderer(assignment)}</div>)}</div>,
}));

const event = (overrides: Partial<RangeEvent> = {}): RangeEvent => ({
  id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2099-09-01",
  location: "מטווח דרום", required_count: 1, reserve_count: 0, status: "planned",
  assignments: [{ id: "a1", soldier_id: "me", is_reserve: false, is_draft: false, attendance_status: "pending", note: null, assignment_reason_code: "manual", assignment_reason_text: "שיבוץ ידני" }],
  ...overrides,
});

function renderDetail(overrides: Partial<React.ComponentProps<typeof RangeDetailContent>> = {}) {
  const props = { event: event(), canManage: false, userId: "me", soldierName: () => "אורי", onExcuse: vi.fn().mockResolvedValue(undefined), onDecide: vi.fn().mockResolvedValue(undefined), onAttendance: vi.fn(), ...overrides };
  return { ...render(<RangeDetailContent {...props} />), props };
}

describe("RangeDetailContent self-excusal", () => {
  it("shows the top-level self-excusal action only for the current user's future confirmed assignment", () => {
    renderDetail();
    expect(screen.getByRole("button", { name: "אני לא אוכל להגיע" })).toBeInTheDocument();
    expect(screen.queryByTestId("excuse-button-a1")).not.toBeInTheDocument();
  });

  it("submits the current user's confirmed assignment from the top-level action", async () => {
    const { props } = renderDetail();
    fireEvent.click(screen.getByRole("button", { name: "אני לא אוכל להגיע" }));
    fireEvent.change(screen.getByLabelText("סיבת היעדרות"), { target: { value: "אירוע משפחתי" } });
    fireEvent.click(screen.getByTestId("submit-excuse-button"));
    await waitFor(() => expect(props.onExcuse).toHaveBeenCalledWith("a1", "אירוע משפחתי"));
  });

  it("hides self-excusal for another soldier, a draft, or a past assignment", () => {
    const { rerender } = renderDetail({ event: event({ assignments: [{ ...event().assignments[0], soldier_id: "other" }] }) });
    expect(screen.queryByRole("button", { name: "אני לא אוכל להגיע" })).not.toBeInTheDocument();
    rerender(<RangeDetailContent {...{ event: event({ assignments: [{ ...event().assignments[0], is_draft: true }] }), canManage: false, userId: "me", soldierName: () => "אורי", onExcuse: vi.fn(), onDecide: vi.fn(), onAttendance: vi.fn() }} />);
    expect(screen.queryByRole("button", { name: "אני לא אוכל להגיע" })).not.toBeInTheDocument();
    rerender(<RangeDetailContent {...{ event: event({ date: "2000-01-01" }), canManage: false, userId: "me", soldierName: () => "אורי", onExcuse: vi.fn(), onDecide: vi.fn(), onAttendance: vi.fn() }} />);
    expect(screen.queryByRole("button", { name: "אני לא אוכל להגיע" })).not.toBeInTheDocument();
  });
});
