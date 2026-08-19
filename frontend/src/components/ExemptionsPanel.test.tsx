import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import ExemptionsPanel from "./ExemptionsPanel";
import * as exemptionsApi from "../api/exemptions";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "u-manager", role: "duty_manager", can_apply_commander_exemption_immediately: true } }),
}));

vi.mock("../api/dutyConfig", () => ({
  listExemptionTypes: vi.fn(() => Promise.resolve([])),
  getAllExemptionDutyTypeMaps: vi.fn(() => Promise.resolve({})),
  listDutyTypes: vi.fn(() => Promise.resolve([])),
}));

vi.mock("../api/exemptions", () => ({
  listExemptions: vi.fn(() => Promise.resolve([
    { id: "ex1", soldier_id: "abc", exemption_type_id: null, start_date: "2020-01-01", end_date: null, reason: null, granted_by: null, revoke_reason: null, revoked_by_name: null },
    { id: "ex2", soldier_id: "abc", exemption_type_id: null, start_date: "2020-01-01", end_date: "2020-01-10", reason: null, granted_by: null, revoke_reason: null, revoked_by_name: null },
  ])),
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
      end_date: "2026-01-05",
      reason: "סיבה",
      status: "pending_duty_manager",
      enrollment_request_id: null,
      decided_by: null,
      decision_note: null,
      created_at: "2026-01-01T00:00:00Z",
      files: [],
      can_approve_commander_step: true,
      can_approve_duty_manager_step: true,
    },
  ])),
  approveExemptionRequestCommanderStep: vi.fn(() => Promise.resolve()),
  approveExemptionRequestDutyManagerStep: vi.fn(() => Promise.resolve()),
  rejectExemptionRequest: vi.fn(() => Promise.resolve({})),
}));

test("indefinite checkbox disables end-date picker", () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
  const checkbox = screen.getByTestId("grant-indefinite");
  const endInput = screen.getByTestId("grant-end");
  expect(endInput).not.toBeDisabled();
  fireEvent.click(checkbox);
  expect(endInput).toBeDisabled();
});

test("shows exemption request history with a pending duty-manager approve button for a duty manager viewer", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
  const row = await screen.findByTestId("exemption-request-row-req-1");
  expect(row).toBeTruthy();
  expect(screen.getByTestId("exemption-request-approve-req-1")).toBeTruthy();
});

test("hides the duty-manager-step approve button for a commander-only viewer", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={false} />);
  await screen.findByTestId("exemption-request-row-req-1");
  expect(screen.queryByTestId("exemption-request-approve-req-1")).toBeNull();
});

test("shows a day-count badge next to expired and request-history date ranges", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);

  const pastList = await screen.findByTestId("exemptions-list-past");
  expect(within(pastList).getByText("(10 ימים)")).toBeTruthy();

  const requestRow = await screen.findByTestId("exemption-request-row-req-1");
  expect(within(requestRow).getByText("(5 ימים)")).toBeTruthy();
});

test("revoking an exemption requires a reason and calls revokeExemption with it", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
  const revokeButton = await screen.findByTestId("revoke-ex1");
  fireEvent.click(revokeButton);

  const confirmButton = screen.getByTestId("reason-modal-confirm");
  expect(confirmButton).toBeDisabled(); // no reason typed yet

  const textarea = screen.getByTestId("reason-modal-textarea");
  fireEvent.change(textarea, { target: { value: "לא רלוונטי" } });
  expect(confirmButton).not.toBeDisabled();

  fireEvent.click(confirmButton);

  await waitFor(() => {
    expect(exemptionsApi.revokeExemption).toHaveBeenCalledWith("abc", "ex1", "לא רלוונטי");
  });
});

test("renders the exemption-request date range in start-then-end order, not reversed", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} canApproveDutyManagerStep={true} />);
  const row = await screen.findByTestId("exemption-request-row-req-1");
  expect(row.textContent).toMatch(/01\.01\.2026[\s\S]*05\.01\.2026/);
});
