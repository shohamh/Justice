import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "../i18n";
import EnrollmentApprovalModal from "./EnrollmentApprovalModal";
import * as rankAdvancementApi from "../api/rankAdvancement";
import * as enrollmentApi from "../api/enrollment";

vi.mock("../api/enrollment", () => ({
  patchEnrollment: vi.fn().mockResolvedValue({}),
  approveEnrollment: vi.fn().mockResolvedValue(undefined),
  rejectEnrollment: vi.fn(),
}));

vi.mock("../api/rankAdvancement", async () => {
  const actual = await vi.importActual<typeof import("../api/rankAdvancement")>("../api/rankAdvancement");
  return { ...actual, getRankLadder: vi.fn() };
});

vi.mocked(rankAdvancementApi.getRankLadder).mockResolvedValue({
  enlisted: [{ rank: "טוראי", months_to_next: null, advance_on_career_entry: false }],
  officer: [{ rank: "סגן", months_to_next: null, advance_on_career_entry: false }],
  officer_academic: [{ rank: "קאב", months_to_next: null, advance_on_career_entry: false }],
});

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const request = {
  id: "enroll-1",
  soldier_id: "soldier-1",
  soldier_name: "Test Soldier",
  soldier_personal_number: "1234567",
  requested_node_id: "node-1",
  requested_node_name: "Unit",
  status: "pending",
  decided_by: null,
  decision_note: null,
  phone: null,
  email: null,
  rank: null,
  is_officer: false,
  is_career: false,
  can_edit_rank_advancement: true,
  rank_track: null,
  gender: null,
  enlistment_date: null,
  enrolled_at: "2026-01-15",
  mandatory_end_date: null,
  discharge_date: null,
  last_mitvahim_date: null,
  last_alal_date: null,
  unit_join_date: null,
  exemption_requests: [],
  nearest_commander: null,
  nearest_duty_manager: null,
};

describe("EnrollmentApprovalModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("stays open when selecting a requested unit", () => {
    const onClose = vi.fn();
    renderWithProviders(
      <EnrollmentApprovalModal
        req={request}
        nodes={[{ id: "node-2", name: "Other Unit" }]}
        exemptionTypes={[]}
        onClose={onClose}
        onDone={vi.fn()}
      />,
    );

    fireEvent.focus(screen.getAllByRole("combobox")[0]);
    fireEvent.click(screen.getByRole("option", { name: "Other Unit" }));

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: /Test Soldier/ })).toBeInTheDocument();
  });

  it("labels a still-pending linked exemption request correctly, not as rejected", () => {
    renderWithProviders(
      <EnrollmentApprovalModal
        req={{
          ...request,
          exemption_requests: [
            { id: "ex-1", exemption_type_id: null, start_date: "2026-01-01", end_date: null, reason: null, status: "pending_commander" },
          ],
        }}
        nodes={[]}
        exemptionTypes={[]}
        onClose={vi.fn()}
        onDone={vi.fn()}
      />,
    );

    expect(screen.getByText("ממתין לאישור מפקד")).toBeInTheDocument();
    expect(screen.queryByText("נדחה")).not.toBeInTheDocument();
  });

  it("does not send rank fields when can_edit_rank_advancement is false, but still approves", async () => {
    const req = { ...request, can_edit_rank_advancement: false, rank: "רב\"ט" };
    renderWithProviders(
      <EnrollmentApprovalModal req={req} nodes={[]} exemptionTypes={[]} onClose={vi.fn()} onDone={vi.fn()} />,
    );

    fireEvent.click(screen.getByText("שמור ואשר"));

    await waitFor(() => {
      expect(enrollmentApi.patchEnrollment).toHaveBeenCalled();
      expect(enrollmentApi.approveEnrollment).toHaveBeenCalledWith(req.id);
    });
    // `req.rank` is non-null here, so a weaker `expect.anything()` check on the
    // `rank` value would pass even if the field were still being sent — assert
    // the keys are absent from the patch payload entirely.
    const patchArg = vi.mocked(enrollmentApi.patchEnrollment).mock.calls[0][1];
    expect(patchArg).not.toHaveProperty("rank");
    expect(patchArg).not.toHaveProperty("is_officer");
    expect(patchArg).not.toHaveProperty("rank_track");
  });

  it("sends rank fields when can_edit_rank_advancement is true", async () => {
    const req = { ...request, can_edit_rank_advancement: true, rank: "רב\"ט" };
    renderWithProviders(
      <EnrollmentApprovalModal req={req} nodes={[]} exemptionTypes={[]} onClose={vi.fn()} onDone={vi.fn()} />,
    );

    fireEvent.click(screen.getByText("שמור ואשר"));

    await waitFor(() => {
      expect(enrollmentApi.patchEnrollment).toHaveBeenCalledWith(
        req.id,
        expect.objectContaining({ rank: 'רב"ט' }),
      );
    });
  });

  it("sends a corrected unit join date before approving enrollment", async () => {
    renderWithProviders(
      <EnrollmentApprovalModal
        req={{ ...request, unit_join_date: "2026-01-01" }}
        nodes={[]}
        exemptionTypes={[]}
        onClose={vi.fn()}
        onDone={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("שמור ואשר"));

    await waitFor(() => {
      expect(enrollmentApi.patchEnrollment).toHaveBeenCalledWith(
        request.id,
        expect.objectContaining({ unit_join_date: "2026-01-01" }),
      );
    });
  });

  it("shows Hebrew validation and does not save a unit join date before enlistment", async () => {
    renderWithProviders(
      <EnrollmentApprovalModal
        req={{
          ...request,
          enlistment_date: "2026-01-02",
          unit_join_date: "2026-01-01",
        }}
        nodes={[]}
        exemptionTypes={[]}
        onClose={vi.fn()}
        onDone={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("שמור ואשר"));

    expect(screen.getByText("תאריך הכניסה ליחידה לא יכול להיות לפני תאריך הגיוס")).toBeInTheDocument();
    expect(enrollmentApi.patchEnrollment).not.toHaveBeenCalled();
    expect(enrollmentApi.approveEnrollment).not.toHaveBeenCalled();
  });
});
