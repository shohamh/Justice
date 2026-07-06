import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ExemptionsPanel from "./ExemptionsPanel";
import * as exemptionsApi from "../api/exemptions";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../api/dutyConfig", () => ({
  listExemptionTypes: vi.fn(() => Promise.resolve([])),
  getAllExemptionDutyTypeMaps: vi.fn(() => Promise.resolve({})),
  listDutyTypes: vi.fn(() => Promise.resolve([])),
}));

vi.mock("../api/exemptions", () => ({
  listExemptions: vi.fn(() => Promise.resolve([
    { id: "ex1", soldier_id: "abc", exemption_type_id: null, start_date: "2020-01-01", end_date: null, reason: null, granted_by: null, revoke_reason: null, revoked_by_name: null },
  ])),
  grantExemption: vi.fn(() => Promise.resolve({})),
  revokeExemption: vi.fn(() => Promise.resolve()),
  grantCommanderExemption: vi.fn(() => Promise.resolve()),
}));

test("indefinite checkbox disables end-date picker", () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} />);
  const checkbox = screen.getByTestId("grant-indefinite");
  const endInput = screen.getByTestId("grant-end");
  expect(endInput).not.toBeDisabled();
  fireEvent.click(checkbox);
  expect(endInput).toBeDisabled();
});

test("revoking an exemption requires a reason and calls revokeExemption with it", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} />);
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
