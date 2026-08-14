import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import "../i18n";
import EnrollmentApprovalModal from "./EnrollmentApprovalModal";
import * as rankAdvancementApi from "../api/rankAdvancement";

vi.mock("../api/enrollment", () => ({
  patchEnrollment: vi.fn(),
  approveEnrollment: vi.fn(),
  rejectEnrollment: vi.fn(),
}));

vi.mock("../api/rankAdvancement", async () => {
  const actual = await vi.importActual<typeof import("../api/rankAdvancement")>("../api/rankAdvancement");
  return { ...actual, getRankLadder: vi.fn() };
});

vi.mocked(rankAdvancementApi.getRankLadder).mockResolvedValue({
  enlisted: [{ rank: "טוראי", months_to_next: null }],
  officer: [{ rank: "סגן", months_to_next: null }],
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
  gender: null,
  enlistment_date: null,
  mandatory_end_date: null,
  discharge_date: null,
  last_mitvahim_date: null,
  last_alal_date: null,
  exemption_requests: [],
  nearest_commander: null,
  nearest_duty_manager: null,
};

describe("EnrollmentApprovalModal", () => {
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
});
