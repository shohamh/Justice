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
}));

test("indefinite checkbox disables end-date picker", () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} />);
  const checkbox = screen.getByTestId("grant-indefinite");
  const endInput = screen.getByTestId("grant-end");
  expect(endInput).not.toBeDisabled();
  fireEvent.click(checkbox);
  expect(endInput).toBeDisabled();
});
