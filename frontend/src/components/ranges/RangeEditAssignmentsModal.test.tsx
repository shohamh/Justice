import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RangeCandidate, RangeCandidatesResponse, RangeEvent } from "../../api/ranges";
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

const candidateResponse = (
  candidates: RangeCandidate[] = [],
  excluded: RangeCandidatesResponse["excluded"] = [],
): RangeCandidatesResponse => ({ candidates, excluded });

function renderModal(overrides: Partial<React.ComponentProps<typeof RangeEditAssignmentsModal>> = {}) {
  const props = {
    open: true, event: event(), soldiers: [soldier("s1", "אורי"), soldier("s2", "דנה")],
    canManage: true, onClose: vi.fn(), onChanged: vi.fn().mockResolvedValue(undefined), ...overrides,
  };
  return { ...render(<RangeEditAssignmentsModal {...props} />), props };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue(candidateResponse());
});

describe("RangeEditAssignmentsModal", () => {
  it("renders primary and reserve assignments in the summary table", () => {
    renderModal({ event: event([assignment("a1", "s1"), assignment("a2", "s2", true, true)]) });
    expect(screen.getAllByText("אורי")).toHaveLength(2);
    expect(screen.getAllByText("דנה")).toHaveLength(2);
    expect(screen.getAllByText("ראשי").length).toBeGreaterThan(0);
    expect(screen.getAllByText("רזרבה").length).toBeGreaterThan(0);
  });

  it("renders Hebrew assignment reasons for automatic and manual assignments", () => {
    renderModal({ event: event([
      assignment("a1", "s1", false, false, "qualified", null),
      assignment("a2", "s2", true, false, "manual", "שיבוץ לפי צורך מבצעי"),
    ]) });
    expect(screen.getAllByText("כשירות תקפה למטווח")).toHaveLength(2);
    expect(screen.getAllByText("שיבוץ לפי צורך מבצעי")).toHaveLength(2);
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
    expect(screen.getAllByText("שיבוץ לפי צורך מבצעי")).toHaveLength(2);
    expect(screen.queryByTestId("edit-assignment-reason-a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("save-assignment-reason-a1")).not.toBeInTheDocument();
  });

  it("keeps the roster visible but hides every assignment mutation control from a non-manager", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue(candidateResponse());
    renderModal({ canManage: false, event: event([assignment("a1", "s1", false, false)]) });

    expect(screen.getAllByText("אורי")).toHaveLength(2);
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
    vi.spyOn(window, "prompt").mockReturnValue("חייל שוחרר");
    vi.mocked(rangesApi.removeRangeAssignment).mockReturnValue(new Promise<void>(r => { resolve = r; }));
    renderModal({ event: event([assignment("a1", "s1")]) });
    fireEvent.click(screen.getByTestId("remove-assignment-a1"));
    expect(screen.getByTestId("remove-assignment-a1")).toBeDisabled();
    resolve();
    await waitFor(() => expect(screen.queryByText("אורי")).not.toBeInTheDocument());
  });

  it("shows a user-facing error when removing an assignment fails", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("חייל שוחרר");
    vi.mocked(rangesApi.removeRangeAssignment).mockRejectedValue(new Error("remove"));
    renderModal({ event: event([assignment("a1", "s1", false, false)]) });
    fireEvent.click(screen.getByTestId("remove-assignment-a1"));
    expect(await screen.findByRole("alert")).toHaveTextContent("הסרת השיבוץ נכשלה");
  });

  it("does not remove an assignment when the reason prompt is cancelled", async () => {
    vi.spyOn(window, "prompt").mockReturnValue(null);
    renderModal({ event: event([assignment("a1", "s1")]) });
    fireEvent.click(screen.getByTestId("remove-assignment-a1"));
    expect(rangesApi.removeRangeAssignment).not.toHaveBeenCalled();
    expect(screen.getAllByText(/אורי/)).toHaveLength(2);
  });

  it("renders the ranked candidate panel with auto-select and lets a manager save a batch", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue(candidateResponse([
      { soldier_id: "s1", full_name: "אורי", personal_number: "s1", reason_code: "qualified", explanation: "qualified", conflict_warning: null },
      { soldier_id: "s2", full_name: "דנה", personal_number: "s2", reason_code: "available_and_balanced", explanation: "available_and_balanced", conflict_warning: null },
      { soldier_id: "s3", full_name: "רון", personal_number: "s3", reason_code: "available_and_balanced", explanation: "available_and_balanced", conflict_warning: null },
    ]));
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

  it("shows excluded candidates and their reasons in a collapsed summary", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue(candidateResponse([], [
      { soldier_id: "s1", soldier_name: "אורי", reason: "weapon_exempt" },
      { soldier_id: "s2", soldier_name: "דנה", reason: "structurally_ineligible" },
      { soldier_id: "s3", soldier_name: "רון", reason: "assigned_elsewhere_same_day" },
    ]));
    renderModal({ event: event([]) });

    const summaries = await screen.findAllByText("ranges.excluded_summary");
    expect(summaries).toHaveLength(2);
    fireEvent.click(summaries[0]);
    expect(await screen.findAllByText("אורי: ranges.excluded_reason.weapon_exempt")).toHaveLength(2);
    expect(screen.getAllByText("דנה: ranges.excluded_reason.structurally_ineligible")).toHaveLength(2);
    expect(screen.getAllByText("רון: ranges.excluded_reason.assigned_elsewhere_same_day")).toHaveLength(2);
  });

  it("does not auto-select any reserve candidates once the reserve slots are already full", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue(candidateResponse([
      { soldier_id: "s1", full_name: "אורי", personal_number: "s1", reason_code: "qualified", explanation: "qualified", conflict_warning: null },
      { soldier_id: "s2", full_name: "דנה", personal_number: "s2", reason_code: "available_and_balanced", explanation: "available_and_balanced", conflict_warning: null },
    ]));
    // reserve_count: 1, and one reserve assignment already fills that slot.
    renderModal({ event: { ...event([assignment("a1", "s3", true)]), reserve_count: 1 } });

    await screen.findByTestId("range-auto-select-reserve");
    expect(screen.getByTestId("range-auto-select-reserve")).toBeDisabled();

    fireEvent.click(screen.getByTestId("range-auto-select-reserve"));
    expect(screen.getByTestId("reserve-candidate-checkbox-s1")).not.toBeChecked();
    expect(screen.getByTestId("reserve-candidate-checkbox-s2")).not.toBeChecked();
  });

  it("disables auto-select once a pending (not-yet-saved) selection already fills the slots", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue(candidateResponse([
      { soldier_id: "s1", full_name: "אורי", personal_number: "s1", reason_code: "qualified", explanation: "qualified", conflict_warning: null },
      { soldier_id: "s2", full_name: "דנה", personal_number: "s2", reason_code: "available_and_balanced", explanation: "available_and_balanced", conflict_warning: null },
    ]));
    renderModal({ event: { ...event([]), required_count: 1 } });

    fireEvent.click(await screen.findByTestId("candidate-checkbox-s1"));
    expect(screen.getByTestId("range-auto-select-primary")).toBeDisabled();

    fireEvent.click(screen.getByTestId("range-auto-select-primary"));
    expect(screen.getByTestId("candidate-checkbox-s2")).not.toBeChecked();
  });

  it("filters the primary candidate list live as the user types in the search box", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue(candidateResponse([
      { soldier_id: "s1", full_name: "אורי", personal_number: "111", reason_code: "qualified", explanation: "qualified", conflict_warning: null },
      { soldier_id: "s2", full_name: "דנה", personal_number: "222", reason_code: "available_and_balanced", explanation: "available_and_balanced", conflict_warning: null },
    ]));
    renderModal({ event: event([]) });

    await screen.findByTestId("candidate-checkbox-s1");
    expect(screen.getByTestId("candidate-checkbox-s2")).toHaveLength(2);

    fireEvent.change(screen.getAllByPlaceholderText("חיפוש...")[0], { target: { value: "דנה" } });

    expect(screen.queryByTestId("candidate-checkbox-s1")).not.toBeInTheDocument();
    expect(screen.getByTestId("candidate-checkbox-s2")).toHaveLength(2);
  });

  it("shows a loading placeholder while candidates are being fetched, not the empty-state message", async () => {
    let resolveCandidates: (value: rangesApi.RangeCandidatesResponse) => void = () => {};
    vi.mocked(rangesApi.getRangeCandidates).mockReturnValue(
      new Promise(resolve => { resolveCandidates = resolve; })
    );
    renderModal({ event: event([]) });

    expect(await screen.findAllByText("טוען רשימת מועמדים...")).toHaveLength(2);
    expect(screen.queryByText("אין מועמדים זמינים")).not.toBeInTheDocument();

    resolveCandidates(candidateResponse());
    expect(await screen.findAllByText("אין מועמדים זמינים")).toHaveLength(2);
  });

  it("shows a conflict-warning badge for a candidate kept despite a scheduling conflict, but leaves them selectable", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue(candidateResponse([
      {
        soldier_id: "s3", full_name: "רון", personal_number: "s3", reason_code: "duty_priority",
        explanation: "תורנות קרובה ב-20.08.2026",
        conflict_warning: "אילוץ מאושר 18.08.2026–20.08.2026",
      },
    ]));
    renderModal({ event: event([]) });

    const checkbox = await screen.findByTestId("candidate-checkbox-s3");
    expect(checkbox).not.toBeDisabled();
    expect(screen.getAllByTitle("אילוץ מאושר 18.08.2026–20.08.2026").length).toBeGreaterThan(0);
    expect(screen.getAllByText("אילוץ מאושר 18.08.2026–20.08.2026").length).toBeGreaterThan(0);
  });

  it("shows a user-facing error when saving the batch fails", async () => {
    vi.mocked(rangesApi.getRangeCandidates).mockResolvedValue(candidateResponse([
      { soldier_id: "s1", full_name: "אורי", personal_number: "s1", reason_code: "qualified", explanation: "qualified", conflict_warning: null },
    ]));
    vi.mocked(rangesApi.batchAssignRange).mockRejectedValue(new Error("batch"));
    renderModal({ event: event([]) });

    fireEvent.click(await screen.findByTestId("candidate-checkbox-s1"));
    fireEvent.click(screen.getByTestId("save-assignments"));
    expect(await screen.findByRole("alert")).toHaveTextContent("שמירת השיבוצים נכשלה");
  });

  it("re-fetches candidates after a successful batch save so a just-assigned soldier is no longer offered", async () => {
    vi.mocked(rangesApi.getRangeCandidates)
      .mockResolvedValueOnce(candidateResponse([
        { soldier_id: "s1", full_name: "אורי", personal_number: "s1", reason_code: "qualified", explanation: "qualified", conflict_warning: null },
      ]))
      .mockResolvedValueOnce(candidateResponse());
    vi.mocked(rangesApi.batchAssignRange).mockResolvedValue([
      { id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false, attendance_status: "pending", note: null, assignment_reason_code: "qualified", assignment_reason_text: null },
    ]);
    renderModal({ event: { ...event([]), required_count: 1 } });

    fireEvent.click(await screen.findByTestId("candidate-checkbox-s1"));
    fireEvent.click(screen.getByTestId("save-assignments"));

    await waitFor(() => expect(rangesApi.getRangeCandidates).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByTestId("candidate-checkbox-s1")).not.toBeInTheDocument());
  });

  it("re-fetches candidates after removing an assignment so the freed soldier becomes selectable again", async () => {
    vi.mocked(rangesApi.getRangeCandidates)
      .mockResolvedValueOnce(candidateResponse())
      .mockResolvedValueOnce(candidateResponse([
        { soldier_id: "s1", full_name: "אורי", personal_number: "s1", reason_code: "qualified", explanation: "qualified", conflict_warning: null },
      ]));
    vi.spyOn(window, "prompt").mockReturnValue("חייל שוחרר");
    vi.mocked(rangesApi.removeRangeAssignment).mockResolvedValue(undefined);
    renderModal({ event: event([assignment("a1", "s1")]) });

    fireEvent.click(screen.getByTestId("remove-assignment-a1"));

    await waitFor(() => expect(rangesApi.getRangeCandidates).toHaveBeenCalledTimes(2));
    expect(await screen.findByTestId("candidate-checkbox-s1")).toHaveLength(2);
  });

  it("reports full primary and reserve capacity and closes explicitly", () => {
    const { props } = renderModal({ event: event([assignment("a1", "s1"), assignment("a2", "s2"), assignment("a3", "s3", true)]) });
    expect(screen.getAllByTestId("range-capacity-full").length).toBe(2);
    fireEvent.click(screen.getAllByRole("button", { name: "סגור" })[1]);
    expect(props.onClose).toHaveBeenCalledOnce();
  });
});
