import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RangeEvent } from "../../api/ranges";
import * as rangesApi from "../../api/ranges";
import { SoldierDTO } from "../../api/soldiers";
import RangeEditAssignmentsModal from "./RangeEditAssignmentsModal";

vi.mock("../../api/ranges");

const soldier = (id: string, full_name: string): SoldierDTO => ({
  id, full_name, personal_number: id, role: "soldier", hierarchy_node_id: "node-1",
  phone: null, must_change_password: false, left_at: null, enrolled_at: null,
  gender: null, is_officer: false, is_career: false, rank: null,
  bahad1_graduate: false, has_military_driving_license: null,
  military_driving_license_expiry: null, enlistment_date: null, mandatory_end_date: null,
  discharge_date: null, last_mitvahim_date: null, last_alal_date: null,
  telegram_linked: false,
});

const event = (assignments: RangeEvent["assignments"] = []): RangeEvent => ({
  id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
  location: "מטווח דרום", required_count: 2, reserve_count: 1, status: "planned", assignments,
});

const assignment = (id: string, soldier_id: string, is_reserve = false, is_draft = false, assignment_reason_code = "manual", assignment_reason_text: string | null = "שיבוץ ידני") => ({
  id, soldier_id, is_reserve, is_draft, attendance_status: "pending" as const, note: null, assignment_reason_code, assignment_reason_text,
});

function renderModal(overrides: Partial<React.ComponentProps<typeof RangeEditAssignmentsModal>> = {}) {
  const props = {
    open: true, event: event(), soldiers: [soldier("s1", "אורי"), soldier("s2", "דנה")],
    canManage: true, onClose: vi.fn(), onChanged: vi.fn().mockResolvedValue(undefined), ...overrides,
  };
  return { ...render(<RangeEditAssignmentsModal {...props} />), props };
}

beforeEach(() => vi.clearAllMocks());

describe("RangeEditAssignmentsModal", () => {
  it("renders primary and reserve sections and marks existing drafts", () => {
    renderModal({ event: event([assignment("a1", "s1"), assignment("a2", "s2", true, true)]) });
    expect(screen.getByTestId("range-primary-assignments")).toBeInTheDocument();
    expect(screen.getByTestId("range-reserve-assignments")).toBeInTheDocument();
    expect(screen.getByTestId("draft-badge-a2")).toBeInTheDocument();
  });

  it("renders Hebrew assignment reasons for automatic and manual assignments", () => {
    renderModal({ event: event([
      assignment("a1", "s1", false, false, "qualified", null),
      assignment("a2", "s2", true, false, "manual", "שיבוץ לפי צורך מבצעי"),
    ]) });
    const reasons = screen.getAllByText(/סיבת השיבוץ:/);
    expect(reasons).toHaveLength(2);
    expect(reasons[0]).toHaveTextContent("כשירות תקפה למטווח");
    expect(reasons[1]).toHaveTextContent("שיבוץ לפי צורך מבצעי");
  });

  it("lets a planner edit and save an assignment explanation", async () => {
    vi.mocked(rangesApi.updateRangeAssignmentReason).mockResolvedValue(
      assignment("a1", "s1", false, false, "manual", "צורך מבצעי")
    );
    const { props } = renderModal({ event: event([assignment("a1", "s1")]) });
    fireEvent.click(screen.getByTestId("edit-assignment-reason-a1"));
    fireEvent.change(screen.getByLabelText("סיבת השיבוץ"), { target: { value: "צורך מבצעי" } });
    fireEvent.click(screen.getByTestId("save-assignment-reason-a1"));
    await waitFor(() => expect(rangesApi.updateRangeAssignmentReason).toHaveBeenCalledWith("event-1", "a1", "manual", "צורך מבצעי"));
    expect(props.onChanged).toHaveBeenCalled();
  });

  it("keeps assignment reasons visible but hides editing controls from a non-manager", () => {
    renderModal({ canManage: false, event: event([assignment("a1", "s1", false, false, "manual", "שיבוץ לפי צורך מבצעי")]) });
    expect(screen.getByText(/סיבת השיבוץ: שיבוץ לפי צורך מבצעי/)).toBeInTheDocument();
    expect(screen.queryByTestId("edit-assignment-reason-a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("save-assignment-reason-a1")).not.toBeInTheDocument();
  });

  it("keeps the roster visible but hides every assignment mutation control from a non-manager", () => {
    renderModal({ canManage: false, event: event([assignment("a1", "s1", false, true)]) });

    expect(screen.getByText("אורי")).toBeInTheDocument();
    expect(screen.queryByTestId("range-auto-assign")).not.toBeInTheDocument();
    expect(screen.queryByTestId("range-confirm-all")).not.toBeInTheDocument();
    expect(screen.queryByTestId("confirm-draft-a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("remove-assignment-a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("range-reserve-toggle")).not.toBeInTheDocument();
    expect(screen.queryByTestId("range-soldier-search")).not.toBeInTheDocument();
    expect(screen.queryByTestId("add-soldier-s2")).not.toBeInTheDocument();
  });

  it("uses a Hebrew fallback instead of exposing raw reason API errors", async () => {
    vi.mocked(rangesApi.updateRangeAssignmentReason).mockRejectedValue({ response: { data: { detail: "custom_reason_text_required" } } });
    renderModal({ event: event([assignment("a1", "s1")]) });
    fireEvent.click(screen.getByTestId("edit-assignment-reason-a1"));
    fireEvent.change(screen.getByLabelText("סיבת השיבוץ"), { target: { value: "סיבה" } });
    fireEvent.click(screen.getByTestId("save-assignment-reason-a1"));
    expect(await screen.findByRole("alert")).toHaveTextContent("יש למלא את סיבת השיבוץ");
    expect(screen.queryByText("custom_reason_text_required")).not.toBeInTheDocument();
  });

  it("uses the Hebrew generic fallback for an unknown reason API error", async () => {
    vi.mocked(rangesApi.updateRangeAssignmentReason).mockRejectedValue({ response: { data: { detail: "unrecognized_reason_policy" } } });
    renderModal({ event: event([assignment("a1", "s1")]) });
    fireEvent.click(screen.getByTestId("edit-assignment-reason-a1"));
    fireEvent.change(screen.getByLabelText("סיבת השיבוץ"), { target: { value: "סיבה" } });
    fireEvent.click(screen.getByTestId("save-assignment-reason-a1"));
    expect(await screen.findByRole("alert")).toHaveTextContent("עדכון סיבת השיבוץ נכשל");
    expect(screen.queryByText("unrecognized_reason_policy")).not.toBeInTheDocument();
  });

  it("adds a soldier with the reserve toggle and refreshes the event", async () => {
    vi.mocked(rangesApi.addRangeAssignment).mockResolvedValue(assignment("a1", "s1", true));
    const { props } = renderModal();
    fireEvent.change(screen.getByTestId("range-soldier-search"), { target: { value: "אורי" } });
    fireEvent.click(screen.getByTestId("range-reserve-toggle"));
    fireEvent.click(screen.getByTestId("add-soldier-s1"));
    await waitFor(() => expect(rangesApi.addRangeAssignment).toHaveBeenCalledWith("event-1", "s1", true));
    expect(props.onChanged).toHaveBeenCalled();
  });

  it("shows pending state while removing an assignment", async () => {
    let resolve!: () => void;
    vi.mocked(rangesApi.removeRangeAssignment).mockReturnValue(new Promise<void>(r => { resolve = r; }));
    renderModal({ event: event([assignment("a1", "s1")]) });
    fireEvent.click(screen.getByTestId("remove-assignment-a1"));
    expect(screen.getByTestId("remove-assignment-a1")).toBeDisabled();
    resolve();
    await waitFor(() => expect(screen.queryByText("אורי")).not.toBeInTheDocument());
  });

  it("supports auto-assignment and confirming one or all drafts", async () => {
    vi.mocked(rangesApi.autoAssignRange).mockResolvedValue({ created: [assignment("a1", "s1", false, true), assignment("a2", "s2", false, true)], shortfall: 0 });
    vi.mocked(rangesApi.confirmDraftAssignment).mockResolvedValue(assignment("a1", "s1"));
    vi.mocked(rangesApi.confirmAllDrafts).mockResolvedValue([]);
    const { props } = renderModal();
    fireEvent.click(screen.getByTestId("range-auto-assign"));
    await waitFor(() => expect(rangesApi.autoAssignRange).toHaveBeenCalledWith("event-1"));
    expect(await screen.findByTestId("draft-badge-a1")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("confirm-draft-a1"));
    await waitFor(() => expect(rangesApi.confirmDraftAssignment).toHaveBeenCalledWith("event-1", "a1"));
    fireEvent.click(screen.getByTestId("range-confirm-all"));
    await waitFor(() => expect(rangesApi.confirmAllDrafts).toHaveBeenCalledWith("event-1"));
    await waitFor(() => expect(props.onChanged).toHaveBeenCalledTimes(3));
  });

  it.each([
    ["add", "add-soldier-s1", "הוספת השיבוץ נכשלה", () => vi.mocked(rangesApi.addRangeAssignment).mockRejectedValue(new Error("add"))],
    ["remove", "remove-assignment-a1", "הסרת השיבוץ נכשלה", () => vi.mocked(rangesApi.removeRangeAssignment).mockRejectedValue(new Error("remove"))],
    ["auto", "range-auto-assign", "השיבוץ האוטומטי נכשל", () => vi.mocked(rangesApi.autoAssignRange).mockRejectedValue(new Error("auto"))],
    ["confirm", "confirm-draft-a1", "אישור השיבוץ נכשל", () => vi.mocked(rangesApi.confirmDraftAssignment).mockRejectedValue(new Error("confirm"))],
  ])("shows a user-facing error when %s fails", async (_name, button, message, configure) => {
    configure();
    renderModal({ event: button === "add-soldier-s1" ? event() : event([assignment("a1", "s1", false, button === "confirm-draft-a1")]) });
    fireEvent.click(screen.getByTestId(button));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("shows an error when confirming all drafts fails", async () => {
    vi.mocked(rangesApi.confirmAllDrafts).mockRejectedValue(new Error("confirm all"));
    renderModal({ event: event([assignment("a1", "s1", false, true)]) });
    fireEvent.click(screen.getByTestId("range-confirm-all"));
    expect(await screen.findByRole("alert")).toHaveTextContent("אישור השיבוצים נכשל");
  });

  it("reports full primary and reserve capacity and closes explicitly", () => {
    const { props } = renderModal({ event: event([assignment("a1", "s1"), assignment("a2", "s2"), assignment("a3", "s3", true)]) });
    expect(screen.getAllByTestId("range-capacity-full").length).toBe(2);
    fireEvent.click(screen.getAllByRole("button", { name: "סגור" })[1]);
    expect(props.onClose).toHaveBeenCalledOnce();
  });
});
