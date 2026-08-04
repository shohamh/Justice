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

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue([]);
});

describe("RangeEditAssignmentsModal", () => {
  it("renders primary and reserve sections and marks existing drafts", () => {
    renderModal({ event: event([assignment("a1", "s1"), assignment("a2", "s2", true, true)]) });
    expect(screen.getByTestId("range-primary-assignments")).toBeInTheDocument();
    expect(screen.getByTestId("range-reserve-assignments")).toBeInTheDocument();
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

  it("keeps the roster visible but hides every assignment mutation control from a non-manager", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue([]);
    renderModal({ canManage: false, event: event([assignment("a1", "s1", false, false)]) });

    expect(screen.getByText("אורי")).toBeInTheDocument();
    expect(screen.queryByTestId("range-auto-select-primary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("save-assignments")).not.toBeInTheDocument();
    expect(screen.queryByTestId("remove-assignment-a1")).not.toBeInTheDocument();
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

  it("shows pending state while removing an assignment", async () => {
    let resolve!: () => void;
    vi.mocked(rangesApi.removeRangeAssignment).mockReturnValue(new Promise<void>(r => { resolve = r; }));
    renderModal({ event: event([assignment("a1", "s1")]) });
    fireEvent.click(screen.getByTestId("remove-assignment-a1"));
    expect(screen.getByTestId("remove-assignment-a1")).toBeDisabled();
    resolve();
    await waitFor(() => expect(screen.queryByText("אורי")).not.toBeInTheDocument());
  });

  it("shows a user-facing error when removing an assignment fails", async () => {
    vi.mocked(rangesApi.removeRangeAssignment).mockRejectedValue(new Error("remove"));
    renderModal({ event: event([assignment("a1", "s1", false, false)]) });
    fireEvent.click(screen.getByTestId("remove-assignment-a1"));
    expect(await screen.findByRole("alert")).toHaveTextContent("הסרת השיבוץ נכשלה");
  });

  it("renders the ranked candidate panel with auto-select and lets a manager save a batch", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue([
      { soldier_id: "s1", full_name: "אורי", personal_number: "s1", reason_code: "qualified", blocked: false, blocked_reason: null },
      { soldier_id: "s2", full_name: "דנה", personal_number: "s2", reason_code: "available_and_balanced", blocked: false, blocked_reason: null },
      { soldier_id: "s3", full_name: "רון", personal_number: "s3", reason_code: "available_and_balanced", blocked: true, blocked_reason: "exempt" },
    ]);
    vi.mocked(rangesApi.batchAssignRange).mockResolvedValue([
      { id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false, attendance_status: "pending", note: null, assignment_reason_code: "qualified", assignment_reason_text: null },
    ]);
    const { props } = renderModal({ event: { ...event([]), required_count: 1 } });

    await screen.findAllByText("אורי");
    fireEvent.click(screen.getByTestId("range-auto-select-primary"));
    expect(screen.getByTestId("candidate-checkbox-s1")).toBeChecked();

    fireEvent.click(screen.getByTestId("save-assignments"));
    await waitFor(() => expect(rangesApi.batchAssignRange).toHaveBeenCalledWith("event-1", { primaries: ["s1"], reserves: [] }));
    expect(props.onChanged).toHaveBeenCalled();
  });

  it("shows blocked candidates but keeps their checkbox disabled", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue([
      { soldier_id: "s3", full_name: "רון", personal_number: "s3", reason_code: "available_and_balanced", blocked: true, blocked_reason: "exempt" },
    ]);
    renderModal({ event: event([]) });

    const checkbox = await screen.findByTestId("candidate-checkbox-s3");
    expect(checkbox).toBeDisabled();
  });

  it("shows a user-facing error when saving the batch fails", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue([
      { soldier_id: "s1", full_name: "אורי", personal_number: "s1", reason_code: "qualified", blocked: false, blocked_reason: null },
    ]);
    vi.mocked(rangesApi.batchAssignRange).mockRejectedValue(new Error("batch"));
    renderModal({ event: event([]) });

    fireEvent.click(await screen.findByTestId("candidate-checkbox-s1"));
    fireEvent.click(screen.getByTestId("save-assignments"));
    expect(await screen.findByRole("alert")).toHaveTextContent("שמירת השיבוצים נכשלה");
  });

  it("reports full primary and reserve capacity and closes explicitly", () => {
    const { props } = renderModal({ event: event([assignment("a1", "s1"), assignment("a2", "s2"), assignment("a3", "s3", true)]) });
    expect(screen.getAllByTestId("range-capacity-full").length).toBe(2);
    fireEvent.click(screen.getAllByRole("button", { name: "סגור" })[1]);
    expect(props.onClose).toHaveBeenCalledOnce();
  });
});
