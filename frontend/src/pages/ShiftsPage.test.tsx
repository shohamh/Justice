import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter, MemoryRouter } from "react-router-dom";
import { ShiftsContent } from "./ShiftsPage";
import * as shiftsApi from "../api/shifts";
import * as dutyConfigApi from "../api/dutyConfig";
import * as hierarchyApi from "../api/hierarchy";
import * as algorithmApi from "../api/algorithm";
import * as templatesApi from "../api/shiftTemplates";
import * as scoringApi from "../api/scoring";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../api/shifts");
vi.mock("../api/dutyConfig");
vi.mock("../api/hierarchy");
vi.mock("../api/algorithm");
vi.mock("../api/shiftTemplates");
vi.mock("../api/scoring");
vi.mock("../components/AlgorithmInlinePanel", () => ({
  default: () => <div data-testid="algorithm-panel" />,
}));
vi.mock("../components/ShiftFormModal", () => ({
  default: () => <div data-testid="shift-form-modal" />,
}));
vi.mock("../components/ShiftEditAssignmentsModal", () => ({
  default: () => <div data-testid="shift-assignments-modal" />,
}));
vi.mock("../components/ShiftTemplateFormModal", () => ({
  default: () => <div data-testid="shift-template-modal" />,
}));
vi.mock("../components/SetResponsibleUnitsModal", () => ({
  default: () => <div data-testid="responsible-modal" />,
}));
vi.mock("../components/SplitInUnitModal", () => ({
  default: () => <div data-testid="split-modal" />,
}));
vi.mock("../components/AutoAssignResponsibilityModal", () => ({
  default: () => <div data-testid="auto-assign-modal" />,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

test("shows a warning indicator for shifts with ineligible_count", async () => {
  const queryClient = createTestQueryClient();
  const mockShift: shiftsApi.DutyShift = {
    id: "shift1",
    duty_type_id: "dt1",
    duty_location_id: "loc1",
    start_date: "2024-01-01",
    end_date: "2024-01-02",
    required_count: 5,
    notes: null,
    assigned_count: 3,
    reserve_assigned_count: 0,
    fill_status: "partial",
    status: "active",
    ineligible_count: 2,
  };

  vi.mocked(shiftsApi.listShifts).mockResolvedValue([mockShift]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.listLocations).mockResolvedValue([]);
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(algorithmApi.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(templatesApi.listTemplates).mockResolvedValue([]);
  vi.mocked(scoringApi.listEligibilityGroups).mockResolvedValue([]);

  render(
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ShiftsContent />
      </QueryClientProvider>
    </BrowserRouter>
  );

  // Wait for the warning indicator to appear (⚠️ with title)
  const indicator = await screen.findByTitle(/חייל\/ים לא כשירים מבחינת הכשרת נשק/);
  expect(indicator).toBeInTheDocument();
  expect(indicator.textContent).toBe("⚠️");
});

test("does not show warning indicator when ineligible_count is 0", async () => {
  const queryClient = createTestQueryClient();
  const mockShift: shiftsApi.DutyShift = {
    id: "shift1",
    duty_type_id: "dt1",
    duty_location_id: "loc1",
    start_date: "2024-01-01",
    end_date: "2024-01-02",
    required_count: 5,
    notes: null,
    assigned_count: 5,
    reserve_assigned_count: 0,
    fill_status: "full",
    status: "active",
    ineligible_count: 0,
  };

  vi.mocked(shiftsApi.listShifts).mockResolvedValue([mockShift]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.listLocations).mockResolvedValue([]);
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(algorithmApi.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(templatesApi.listTemplates).mockResolvedValue([]);
  vi.mocked(scoringApi.listEligibilityGroups).mockResolvedValue([]);

  render(
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ShiftsContent />
      </QueryClientProvider>
    </BrowserRouter>
  );

  // Wait for the table to render, then verify no warning indicator with that title
  await screen.findByTestId("shifts-page");
  const indicator = screen.queryByTitle(/חייל\/ים לא כשירים מבחינת הכשרת נשק/);
  expect(indicator).not.toBeInTheDocument();
});

test("filters planning rows to weapon-ineligible shifts from the query parameter", async () => {
  const queryClient = createTestQueryClient();
  const ineligibleShift: shiftsApi.DutyShift = {
    id: "ineligible-shift",
    duty_type_id: "dt1",
    duty_location_id: "loc1",
    start_date: "2024-01-01",
    end_date: "2024-01-02",
    required_count: 5,
    notes: null,
    assigned_count: 3,
    reserve_assigned_count: 0,
    fill_status: "partial",
    status: "active",
    ineligible_count: 2,
  };
  const eligibleShift: shiftsApi.DutyShift = {
    ...ineligibleShift,
    id: "eligible-shift",
    ineligible_count: 0,
  };

  vi.mocked(shiftsApi.listShifts).mockResolvedValue([ineligibleShift, eligibleShift]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.listLocations).mockResolvedValue([]);
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(algorithmApi.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(templatesApi.listTemplates).mockResolvedValue([]);
  vi.mocked(scoringApi.listEligibilityGroups).mockResolvedValue([]);

  render(
    <MemoryRouter initialEntries={["/planning/shifts?filter=weapon_ineligible"]}>
      <QueryClientProvider client={queryClient}>
        <ShiftsContent />
      </QueryClientProvider>
    </MemoryRouter>
  );

  expect(await screen.findByTestId("ineligible-shift")).toBeInTheDocument();
  expect(screen.queryByTestId("eligible-shift")).not.toBeInTheDocument();
});

test("selecting a duty type in the quick filter checks all matching shift rows", async () => {
  const queryClient = createTestQueryClient();
  const s1: shiftsApi.DutyShift = {
    id: "s1",
    duty_type_id: "dt1",
    duty_location_id: "loc1",
    start_date: "2024-01-01",
    end_date: "2024-01-02",
    required_count: 5,
    notes: null,
    assigned_count: 0,
    reserve_assigned_count: 0,
    fill_status: "empty",
    status: "active",
    ineligible_count: 0,
  };
  const s2: shiftsApi.DutyShift = { ...s1, id: "s2", duty_type_id: "dt2" };

  vi.mocked(shiftsApi.listShifts).mockResolvedValue([s1, s2]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([
    { id: "dt1", name: "שמירה" }, { id: "dt2", name: "מטבח" },
  ] as never);
  vi.mocked(dutyConfigApi.listLocations).mockResolvedValue([]);
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(algorithmApi.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(templatesApi.listTemplates).mockResolvedValue([]);
  vi.mocked(scoringApi.listEligibilityGroups).mockResolvedValue([]);

  render(
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ShiftsContent />
      </QueryClientProvider>
    </BrowserRouter>
  );

  const user = userEvent.setup();
  const dutyTypeSelect = await screen.findByTestId("quick-filter-duty-type");
  await waitFor(() => {
    expect(Array.from(dutyTypeSelect.options).map(o => o.value)).toEqual(["dt1", "dt2"]);
  });
  await user.selectOptions(dutyTypeSelect, ["dt1"]);
  expect(screen.getByTestId("shift-row-checkbox-s1")).toBeChecked();
  expect(screen.getByTestId("shift-row-checkbox-s2")).not.toBeChecked();
});

test("selecting an eligibility group checks all shift rows whose duty type is in the group", async () => {
  const queryClient = createTestQueryClient();
  const s1: shiftsApi.DutyShift = {
    id: "s1",
    duty_type_id: "dt1",
    duty_location_id: "loc1",
    start_date: "2024-01-01",
    end_date: "2024-01-02",
    required_count: 5,
    notes: null,
    assigned_count: 0,
    reserve_assigned_count: 0,
    fill_status: "empty",
    status: "active",
    ineligible_count: 0,
  };
  const s2: shiftsApi.DutyShift = { ...s1, id: "s2", duty_type_id: "dt2" };

  vi.mocked(shiftsApi.listShifts).mockResolvedValue([s1, s2]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([
    { id: "dt1", name: "שמירה" }, { id: "dt2", name: "מטבח" },
  ] as never);
  vi.mocked(dutyConfigApi.listLocations).mockResolvedValue([]);
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(algorithmApi.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(templatesApi.listTemplates).mockResolvedValue([]);
  vi.mocked(scoringApi.listEligibilityGroups).mockResolvedValue([
    { duty_type_ids: ["dt1"], duty_type_names: ["שמירה"], soldier_count: 12 },
  ]);

  render(
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ShiftsContent />
      </QueryClientProvider>
    </BrowserRouter>
  );

  const user = userEvent.setup();
  await user.selectOptions(await screen.findByTestId("quick-filter-eligibility-group"), ["0"]);
  expect(screen.getByTestId("shift-row-checkbox-s1")).toBeChecked();
  expect(screen.getByTestId("shift-row-checkbox-s2")).not.toBeChecked();
});
