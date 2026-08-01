import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EnrollmentApprovalModal from "./EnrollmentApprovalModal";

vi.mock("../api/enrollment", () => ({
  patchEnrollment: vi.fn(),
  approveEnrollment: vi.fn(),
  rejectEnrollment: vi.fn(),
}));

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
    render(
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
});
