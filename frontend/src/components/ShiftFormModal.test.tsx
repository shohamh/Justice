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
const mockGetQuotaSplitPreview = vi.fn(() =>
  Promise.resolve([
    { hierarchy_node_id: "n1", node_name: "פלוגה א", count: 3, weight: 6 },
    { hierarchy_node_id: "n2", node_name: "פלוגה ב", count: 2, weight: 4 },
  ])
);
vi.mock("../api/shifts", async () => {
  const actual = await vi.importActual<typeof import("../api/shifts")>("../api/shifts");
  return {
    ...actual,
    createShift: (...args: unknown[]) => mockCreateShift(...args),
    updateShift: (...args: unknown[]) => mockUpdateShift(...args),
    setShiftQuotas: vi.fn(() => Promise.resolve({ quotas: [] })),
    getQuotaSplitPreview: (...args: unknown[]) => mockGetQuotaSplitPreview(...args),
  };
});

vi.mock("../api/dutyConfig", () => ({
  createLocation: vi.fn(),
}));

vi.mock("../api/publicSettings", () => ({
  getPublicSettings: vi.fn(() => Promise.resolve({})),
}));

vi.mock("../api/algorithm", () => ({
  submitJob: vi.fn(() => Promise.resolve({ id: "job-1", status: "queued" })),
  getAlgorithmDefaults: vi.fn(() => Promise.resolve({ T: 8, Wt: 14, R: 15, Wr: 28 })),
}));

const mockNodes = [
  {
    id: "root", name: "אוגדה", path_ids: ["root"], children: [
      { id: "n1", name: "פלוגה א", path_ids: ["root", "n1"], children: [] },
      { id: "n2", name: "פלוגה ב", path_ids: ["root", "n2"], children: [] },
    ],
  },
];
vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn(() => Promise.resolve(mockNodes)),
}));

const dutyTypes = [{ id: "d1", name: "duty1", eligible_node_ids: [] }];
const locations = [{ id: "l1", name: "loc1" }];

beforeEach(() => {
  mockCreateShift.mockClear();
  mockUpdateShift.mockClear();
  mockGetQuotaSplitPreview.mockClear();
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

test("shows the common-ancestor label when 2+ quota rows share a parent", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(screen.getByText(/quotas_add/));
  fireEvent.click(screen.getByText(/quotas_add/));
  const selects = screen.getAllByLabelText("shifts.quotas_select_node");
  fireEvent.change(selects[0], { target: { value: "n1" } });
  fireEvent.change(selects[1], { target: { value: "n2" } });

  expect(await screen.findByText("shifts.quotas_common_ancestor")).toBeInTheDocument();
});

test("hides the common-ancestor label with fewer than 2 quota rows", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(screen.getByText(/quotas_add/));
  const select = screen.getAllByLabelText("shifts.quotas_select_node")[0];
  fireEvent.change(select, { target: { value: "n1" } });

  expect(screen.queryByText("shifts.quotas_common_ancestor")).not.toBeInTheDocument();
});

test("split-by-potential button is hidden until exactly one scope node is selected", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  expect(screen.queryByText("shifts.quotas_split_by_potential")).not.toBeInTheDocument();

  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה א" }));
  expect(await screen.findByText("shifts.quotas_split_by_potential")).toBeInTheDocument();

  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה ב" }));
  expect(screen.queryByText("shifts.quotas_split_by_potential")).not.toBeInTheDocument();
});

test("clicking split-by-potential populates quota rows from the API response", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה א" }));
  fireEvent.click(await screen.findByText("shifts.quotas_split_by_potential"));

  await waitFor(() => expect(mockGetQuotaSplitPreview).toHaveBeenCalledWith("n1", 1));
  const counts = await screen.findAllByTestId("quota-count-input");
  expect(counts.map((el) => (el as HTMLInputElement).value)).toEqual(["3", "2"]);
});

test("clicking split-by-potential again (recompute) overwrites existing rows", async () => {
  mockGetQuotaSplitPreview
    .mockResolvedValueOnce([{ hierarchy_node_id: "n1", node_name: "פלוגה א", count: 1, weight: 1 }])
    .mockResolvedValueOnce([{ hierarchy_node_id: "n1", node_name: "פלוגה א", count: 4, weight: 8 }]);

  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());
  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה א" }));

  const splitButton = await screen.findByText("shifts.quotas_split_by_potential");
  fireEvent.click(splitButton);
  await waitFor(async () =>
    expect((await screen.findAllByTestId("quota-count-input"))[0]).toHaveValue(1)
  );

  fireEvent.click(splitButton);
  await waitFor(async () =>
    expect((await screen.findAllByTestId("quota-count-input"))[0]).toHaveValue(4)
  );
  expect(await screen.findAllByTestId("quota-count-input")).toHaveLength(1);
});

test("auto-splits quota rows when the system setting is enabled and a single node is selected", async () => {
  const { getPublicSettings } = await import("../api/publicSettings");
  vi.mocked(getPublicSettings).mockResolvedValueOnce({ "shifts.auto_split_node_quotas": true });

  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה א" }));

  await waitFor(() => expect(mockGetQuotaSplitPreview).toHaveBeenCalled());
  const counts = await screen.findAllByTestId("quota-count-input");
  expect(counts.map((el) => (el as HTMLInputElement).value)).toEqual(["3", "2"]);
  expect(screen.getByText("shifts.quotas_auto_split_hint")).toBeInTheDocument();
});

test("does not auto-split when the system setting is disabled", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה א" }));

  await new Promise((r) => setTimeout(r, 500));
  expect(mockGetQuotaSplitPreview).not.toHaveBeenCalled();
});

test("rerun-algorithm button is hidden for a new (unsaved) shift", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());
  expect(screen.queryByText("shifts.rerun_algorithm")).not.toBeInTheDocument();
});

test("rerun-algorithm button submits a job scoped to the existing shift", async () => {
  const { submitJob } = await import("../api/algorithm");
  const existingShift = {
    id: "shift-42",
    duty_type_id: "d1",
    duty_location_id: "l1",
    start_date: "2026-07-01",
    end_date: "2026-07-02",
    required_count: 3,
    notes: null,
    assigned_count: 0,
    reserve_assigned_count: 0,
    fill_status: "empty" as const,
    status: "active" as const,
    node_quotas: [],
  };

  render(
    <ShiftFormModal
      dutyTypes={dutyTypes}
      locations={locations}
      existing={existingShift}
      onSaved={() => {}}
      onClose={() => {}}
    />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(await screen.findByText("shifts.rerun_algorithm"));

  await waitFor(() =>
    expect(submitJob).toHaveBeenCalledWith(
      expect.objectContaining({ shift_ids: ["shift-42"], mode: "shadow" })
    )
  );
  expect(await screen.findByText(/rerun_algorithm_success/)).toBeInTheDocument();
});
