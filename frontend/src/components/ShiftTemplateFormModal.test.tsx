import { render, screen, fireEvent } from "@testing-library/react";
import ShiftTemplateFormModal from "./ShiftTemplateFormModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { count?: number }) =>
      key === "shift_templates.auto_roll_until_count" ? `count:${opts?.count}` : key,
  }),
}));

vi.mock("../api/shiftTemplates", () => ({
  createTemplate: vi.fn(() => Promise.resolve({})),
  updateTemplate: vi.fn(() => Promise.resolve({})),
}));

const dutyTypes = [{ id: "d1", name: "duty1" }];
const locations = [{ id: "l1", name: "loc1" }];

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-06-19T12:00:00Z")); // Friday
});

afterEach(() => {
  vi.useRealTimers();
});

test("checking auto_roll reveals the until-date picker", () => {
  render(
    <ShiftTemplateFormModal dutyTypes={dutyTypes} locations={locations} onSubmit={() => {}} onClose={() => {}} />
  );
  expect(screen.queryByTestId("auto-roll-until-date")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("auto-roll-checkbox"));
  expect(screen.getByTestId("auto-roll-until-date")).toBeInTheDocument();
});

test("picking an until-date shows the computed instance count for the default weekdays recurrence", () => {
  render(
    <ShiftTemplateFormModal dutyTypes={dutyTypes} locations={locations} onSubmit={() => {}} onClose={() => {}} />
  );
  fireEvent.click(screen.getByTestId("auto-roll-checkbox"));
  fireEvent.change(screen.getByTestId("auto-roll-until-date"), { target: { value: "26/06/2026" } });
  // Default recurrence is "weekdays" (Sun-Thu). Today=2026-06-19 (Fri) .. 2026-06-26 (Fri):
  // matching days are Sun 6/21, Mon 6/22, Tue 6/23, Wed 6/24, Thu 6/25 = 5.
  expect(screen.getByTestId("auto-roll-until-count")).toHaveTextContent("count:5");
});
