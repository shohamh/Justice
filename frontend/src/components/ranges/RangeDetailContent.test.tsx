import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import RangeDetailContent from "./RangeDetailContent";
import { RangeEvent } from "../../api/ranges";

vi.mock("../planning", () => ({
  RosterSection: ({ assignments, assignmentActionRenderer }: { assignments: Array<{ id: string; status?: React.ReactNode }>; assignmentActionRenderer: (assignment: { id: string }) => React.ReactNode }) => <div>{assignments.map(assignment => <div key={assignment.id}>{assignment.status}{assignmentActionRenderer(assignment)}</div>)}</div>,
}));

vi.mock("../../api/ranges", async () => {
  const actual = await vi.importActual<typeof import("../../api/ranges")>("../../api/ranges");
  return { ...actual, markRangeAttendance: vi.fn() };
});

vi.mock("../SoldierLink", () => ({
  default: ({ id, name }: { id: string; name: string }) => <button type="button" data-testid={`soldier-link-${id}`}>{name}</button>,
}));

const event = (overrides: Partial<RangeEvent> = {}): RangeEvent => ({
  id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2099-09-01",
  location: "מטווח דרום", required_count: 1, reserve_count: 0, status: "planned",
  assignments: [{ id: "a1", soldier_id: "me", is_reserve: false, is_draft: false, attendance_status: "pending", note: null, assignment_reason_code: "manual", assignment_reason_text: "שיבוץ ידני" }],
  ...overrides,
});

function baseProps(overrides: Partial<React.ComponentProps<typeof RangeDetailContent>> = {}): React.ComponentProps<typeof RangeDetailContent> {
  return { event: event(), canManage: false, userId: "me", soldierName: () => "אורי", onExcuse: vi.fn().mockResolvedValue(undefined), onDecide: vi.fn().mockResolvedValue(undefined), onAttendance: vi.fn(), ...overrides };
}

function renderDetail(overrides: Partial<React.ComponentProps<typeof RangeDetailContent>> = {}) {
  const props = baseProps(overrides);
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

describe("RangeDetailContent attendance permissions", () => {
  it("hides attendance mutations when the API denies attendance editing", () => {
    renderDetail({ canManage: true, canEditAttendance: false, event: event({ date: "2000-01-01", status: "completed" }) });

    expect(screen.queryByTestId("present-a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("no-show-a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("attendance-save-button")).not.toBeInTheDocument();
  });

  it("allows attendance mutations when the API grants attendance editing", () => {
    renderDetail({ canManage: false, canEditAttendance: true, event: event({ date: "2000-01-01", status: "completed" }) });

    expect(screen.getByTestId("present-a1")).toBeInTheDocument();
    expect(screen.getByTestId("no-show-a1")).toBeInTheDocument();
    expect(screen.getByTestId("attendance-save-button")).toBeInTheDocument();
  });
});

describe("RangeDetailContent attendance saving", () => {
  it("saves all pending attendance changes with a single save button", async () => {
    const rangesApi = await import("../../api/ranges");
    vi.mocked(rangesApi.markRangeAttendance).mockResolvedValue({ id: "a1", soldier_id: "me", is_reserve: false, is_draft: false, attendance_status: "present", note: null, assignment_reason_code: null, assignment_reason_text: null });
    const { props } = renderDetail({ canManage: false, canEditAttendance: true, event: event({ date: "2000-01-01", status: "completed" }) });

    const saveButton = screen.getByTestId("attendance-save-button");
    expect(saveButton).toBeDisabled();

    fireEvent.click(screen.getByTestId("present-a1"));
    expect(saveButton).not.toBeDisabled();
    fireEvent.click(saveButton);

    await waitFor(() => expect(rangesApi.markRangeAttendance).toHaveBeenCalledWith("event-1", "a1", "present", undefined));
    await waitFor(() => expect(props.onAttendance).toHaveBeenCalled());
  });

  it("requires a note before a no-show can be saved", () => {
    renderDetail({ canManage: false, canEditAttendance: true, event: event({ date: "2000-01-01", status: "completed" }) });

    fireEvent.click(screen.getByTestId("no-show-a1"));
    expect(screen.getByTestId("attendance-save-button")).toBeDisabled();

    fireEvent.change(screen.getByTestId("note-a1"), { target: { value: "לא הגיע" } });
    expect(screen.getByTestId("attendance-save-button")).not.toBeDisabled();
  });

  it("shows the saved no-show status and the reason recorded for it", () => {
    renderDetail({
      event: event({
        assignments: [{ id: "a1", soldier_id: "me", is_reserve: false, is_draft: false, attendance_status: "no_show", note: "חופשה מאושרת", assignment_reason_code: "manual", assignment_reason_text: "שיבוץ ידני" }],
      }),
    });

    expect(screen.getByText("לא נכח — חופשה מאושרת")).toBeInTheDocument();
  });
});

describe("RangeDetailContent assignment actions", () => {
  it("never renders an edit-assignments entry point — that's reached via the row action now", () => {
    render(<RangeDetailContent {...baseProps({ canManage: true })} />);
    expect(screen.queryByTestId("edit-range-assignments")).not.toBeInTheDocument();
    expect(screen.queryByText("פעולות שיבוץ")).not.toBeInTheDocument();
  });
});

describe("RangeDetailContent responsible duty manager", () => {
  it("shows the responsible duty manager as a soldier link", () => {
    renderDetail({ event: event({ responsible_duty_manager_id: "responsible-1" }), soldierName: () => "רונן" });
    expect(screen.getByTestId("range-detail-responsible")).toBeInTheDocument();
    expect(screen.getByTestId("soldier-link-responsible-1")).toHaveTextContent("רונן");
  });

  it("shows a dash when no one is responsible", () => {
    renderDetail({ event: event({ responsible_duty_manager_id: null }) });
    expect(screen.getByTestId("range-detail-responsible")).toHaveTextContent("—");
  });
});

describe("RangeDetailContent food summary", () => {
  it("shows separate primary and reserve food counts and special constraints to duty managers", () => {
    const foodSummary = {
      primary: { counts: { regular: 1, vegetarian: 1, vegan: 0, gluten_free: 0, kosher_le_mehadrin: 0, unspecified: 0 }, special_constraints: [{ soldier_id: "s1", soldier_name: "Dana", food_type: "vegetarian", constraint: "Peanut allergy" }] },
      reserve: { counts: { regular: 0, vegetarian: 0, vegan: 1, gluten_free: 0, kosher_le_mehadrin: 0, unspecified: 0 }, special_constraints: [{ soldier_id: "s2", soldier_name: "Yuval", food_type: "vegan", constraint: "No soy" }] },
    };
    renderDetail({ canManage: true, isDutyManager: true, event: event({ food_summary: foodSummary } as Partial<RangeEvent>) });
    expect(screen.getByTestId("range-food-summary")).toBeInTheDocument();
    expect(screen.getByTestId("range-food-primary")).toHaveTextContent("1");
    expect(screen.getByTestId("range-food-reserve")).toHaveTextContent("1");
    expect(screen.getByText("Dana")).toBeInTheDocument();
    expect(screen.getByText("Peanut allergy")).toBeInTheDocument();
    expect(screen.getByText("Yuval")).toBeInTheDocument();
    expect(screen.getByText("No soy")).toBeInTheDocument();
  });

  it("does not show the food summary to non-duty managers", () => {
    renderDetail({ event: event({ food_summary: { primary: { counts: {}, special_constraints: [] }, reserve: { counts: {}, special_constraints: [] } } } as Partial<RangeEvent>), isDutyManager: false });
    expect(screen.queryByTestId("range-food-summary")).not.toBeInTheDocument();
  });
});
