import { render, screen, fireEvent } from "@testing-library/react";
import ExemptionsPanel from "./ExemptionsPanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../api/dutyConfig", () => ({
  listExemptionTypes: vi.fn(() => Promise.resolve([])),
  getAllExemptionDutyTypeMaps: vi.fn(() => Promise.resolve({})),
  listDutyTypes: vi.fn(() => Promise.resolve([])),
}));

vi.mock("../api/exemptions", () => ({
  listExemptions: vi.fn(() => Promise.resolve([])),
  grantExemption: vi.fn(() => Promise.resolve({})),
  revokeExemption: vi.fn(() => Promise.resolve()),
  grantCommanderExemption: vi.fn(() => Promise.resolve()),
  escalateCommanderExemption: vi.fn(() => Promise.resolve({})),
  listExemptionRequestsForSoldier: vi.fn(() => Promise.resolve([
    {
      id: "req-1",
      soldier_id: "abc",
      soldier_name: "X",
      node_name: null,
      exemption_type_id: "et-1",
      start_date: "2026-01-01",
      end_date: null,
      reason: "סיבה",
      status: "pending_duty_manager",
      enrollment_request_id: null,
      decided_by: null,
      decision_note: null,
      created_at: "2026-01-01T00:00:00Z",
      files: [],
    },
  ])),
  approveExemptionRequestCommanderStep: vi.fn(() => Promise.resolve()),
  approveExemptionRequestDutyManagerStep: vi.fn(() => Promise.resolve()),
  rejectExemptionRequest: vi.fn(() => Promise.resolve({})),
}));

test("indefinite checkbox disables end-date picker", () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} />);
  const checkbox = screen.getByTestId("grant-indefinite");
  const endInput = screen.getByTestId("grant-end");
  expect(endInput).not.toBeDisabled();
  fireEvent.click(checkbox);
  expect(endInput).toBeDisabled();
});

test("shows exemption request history with a pending duty-manager approve button", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} />);
  const row = await screen.findByTestId("exemption-request-row-req-1");
  expect(row).toBeTruthy();
  expect(screen.getByTestId("exemption-request-approve-req-1")).toBeTruthy();
});
