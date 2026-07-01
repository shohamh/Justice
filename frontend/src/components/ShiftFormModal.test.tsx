import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ShiftFormModal from "./ShiftFormModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (key === "shifts.quotas_over_allocated") {
        return `over-allocated:${opts?.total}/${opts?.required}`;
      }
      return key;
    },
  }),
}));

const mockCreateShift = vi.fn(() => Promise.resolve({ id: "new-shift-1" }));
const mockUpdateShift = vi.fn(() => Promise.resolve({}));
vi.mock("../api/shifts", async () => {
  const actual = await vi.importActual<typeof import("../api/shifts")>("../api/shifts");
  return {
    ...actual,
    createShift: (...args: unknown[]) => mockCreateShift(...args),
    updateShift: (...args: unknown[]) => mockUpdateShift(...args),
    setShiftQuotas: vi.fn(() => Promise.resolve({ quotas: [] })),
  };
});

vi.mock("../api/dutyConfig", () => ({
  createLocation: vi.fn(),
}));

const mockNodes = [
  { id: "n1", name: "פלוגה א", children: [] },
  { id: "n2", name: "פלוגה ב", children: [] },
];
vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn(() => Promise.resolve(mockNodes)),
}));

const dutyTypes = [{ id: "d1", name: "duty1", eligible_node_ids: [] }];
const locations = [{ id: "l1", name: "loc1" }];

beforeEach(() => {
  mockCreateShift.mockClear();
  mockUpdateShift.mockClear();
});

test("allows adding a node quota row", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());
  fireEvent.click(screen.getByText(/quotas_add/));
  expect(screen.getAllByLabelText("shifts.quotas_select_node").length).toBe(1);
});

test("shows a warning when quota total exceeds required_count", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  // required_count default is 1
  fireEvent.click(screen.getByText(/quotas_add/));

  const rowCountInput = screen.getAllByTestId("quota-count-input")[0];
  fireEvent.change(rowCountInput, { target: { value: "5" } });

  expect(screen.getByText(/over-allocated:5\/1/)).toBeInTheDocument();
});
