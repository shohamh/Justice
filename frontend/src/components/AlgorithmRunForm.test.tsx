import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import AlgorithmRunForm from "./AlgorithmRunForm";
import { checkAvailability, getAlgorithmDefaults, submitJob } from "../api/algorithm";
import { listShifts } from "../api/shifts";
import { fetchHierarchyBranchPage } from "../api/hierarchy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../api/algorithm", () => ({
  checkAvailability: vi.fn(),
  submitJob: vi.fn(),
  getAlgorithmDefaults: vi.fn(),
}));
vi.mock("../api/shifts", () => ({
  listShifts: vi.fn(),
}));
vi.mock("../api/hierarchy", () => ({
  fetchHierarchyBranchPage: vi.fn(),
  isStaleHierarchyCursorError: vi.fn(() => false),
}));
vi.mock("../api/auth", () => ({ getTransparencyAuthorizationScope: () => "viewer-scope" }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { id: "viewer", role: "admin", scope_root_ids: [], active_deputy_grants: [] }, authScopeReady: true }) }));

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={queryClient}><AlgorithmRunForm dutyTypes={[]} onJobSubmitted={vi.fn()} /></QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listShifts).mockResolvedValue([]);
  vi.mocked(fetchHierarchyBranchPage).mockResolvedValue({ items: [], next_cursor: null, has_more: false });
  vi.mocked(checkAvailability).mockResolvedValue({ has_shortage: false, items: [] });
  vi.mocked(submitJob).mockResolvedValue({ id: "job-1", status: "pending" });
});

describe("AlgorithmRunForm - defaults load failure", () => {
  it("fetches the hierarchy only when the subtree disclosure opens and preserves selection", async () => {
    vi.mocked(getAlgorithmDefaults).mockResolvedValue({ T: 5, Wt: 10, R: 12, Wr: 20, enforce_weapon_qualification: false });
    vi.mocked(fetchHierarchyBranchPage).mockResolvedValue({ items: [{ id: "node-1", name: "First Unit", level: "unit", parent_id: null, commander_id: null, commander_name: null, path_ids: ["node-1"], duty_managers: [], dm_manageable: false, can_edit: false, has_children: false }], next_cursor: null, has_more: false });
    vi.mocked(listShifts).mockResolvedValue([{
      id: "shift-1", duty_type_id: "duty-1", duty_location_id: "location-1",
      start_date: "2026-09-17", end_date: "2026-09-18", required_count: 1,
      notes: null, assigned_count: 0, reserve_assigned_count: 0,
      fill_status: "empty", status: "active", ineligible_count: 0,
    }]);
    renderForm();
    await screen.findByRole("checkbox", { name: /duty-1/ });
    expect(fetchHierarchyBranchPage).not.toHaveBeenCalled();
    const disclosure = screen.getByText("algorithm.restrict_to_subtree");
    fireEvent.click(disclosure);
    expect(await screen.findByRole("checkbox", { name: "First Unit" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "First Unit" }));
    fireEvent.click(disclosure);
    fireEvent.click(disclosure);
    expect(screen.getByRole("checkbox", { name: "First Unit" })).toBeChecked();
    expect(fetchHierarchyBranchPage).toHaveBeenCalledTimes(1);
    expect(fetchHierarchyBranchPage).toHaveBeenCalledWith(expect.objectContaining({ parentId: null }));
    fireEvent.click(screen.getByRole("checkbox", { name: /duty-1/ }));
    fireEvent.click(screen.getByRole("button", { name: /algorithm.run_button/ }));
    await waitFor(() => expect(submitJob).toHaveBeenCalledWith(expect.objectContaining({
      settings: expect.objectContaining({ eligible_node_ids: ["node-1"] }),
    })));
  });
  it("shows hierarchy load failure and retries until the tree is available", async () => {
    vi.mocked(getAlgorithmDefaults).mockResolvedValue({ T: 5, Wt: 10, R: 12, Wr: 20, enforce_weapon_qualification: false });
    vi.mocked(listShifts).mockResolvedValue([{
      id: "shift-1", duty_type_id: "duty-1", duty_location_id: "location-1",
      start_date: "2026-09-17", end_date: "2026-09-18", required_count: 1,
      notes: null, assigned_count: 0, reserve_assigned_count: 0,
      fill_status: "empty", status: "active", ineligible_count: 0,
    }]);
    let rejectFirstTreeRequest!: (reason: unknown) => void;
    vi.mocked(fetchHierarchyBranchPage)
      .mockImplementationOnce(() => new Promise((_, reject) => { rejectFirstTreeRequest = reject; }))
      .mockResolvedValueOnce({ items: [{ id: "node-1", name: "First Unit", level: "unit", parent_id: null, commander_id: null, commander_name: null, path_ids: ["node-1"], duty_managers: [], dm_manageable: false, can_edit: false, has_children: false }], next_cursor: null, has_more: false });

    renderForm();
    await screen.findByRole("checkbox", { name: /duty-1/ });
    fireEvent.click(screen.getByText("algorithm.restrict_to_subtree"));
    expect(await screen.findByText("team.hierarchy_loading")).toBeInTheDocument();
    await act(async () => rejectFirstTreeRequest(new Error("Hierarchy unavailable")));

    expect(await screen.findByRole("alert")).toHaveTextContent("team.hierarchy_load_failed");
    fireEvent.click(screen.getByRole("button", { name: "team.hierarchy_retry" }));

    expect(await screen.findByRole("checkbox", { name: "First Unit" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchHierarchyBranchPage).toHaveBeenCalledTimes(2);
  });
  it("surfaces a load error and keeps the hardcoded fallback settings when defaults fail to load", async () => {
    vi.mocked(getAlgorithmDefaults).mockRejectedValue(new Error("Invalid algorithm defaults response"));

    renderForm();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("algorithm.defaults_load_error");
    });
  });

  it("does not show a load error when defaults load successfully", async () => {
    vi.mocked(getAlgorithmDefaults).mockResolvedValue({
      T: 5,
      Wt: 10,
      R: 12,
      Wr: 20,
      enforce_weapon_qualification: false,
    });

    renderForm();

    await waitFor(() => {
      expect(getAlgorithmDefaults).toHaveBeenCalled();
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "algorithm.settings" }));
    expect(screen.getByRole("checkbox", { name: /\u05db\u05e9\u05d9\u05e8\u05d5\u05ea.*\u05e0\u05e9\u05e7/ })).not.toBeChecked();
  });

  it("submits the fetched false range-qualification default explicitly", async () => {
    vi.mocked(getAlgorithmDefaults).mockResolvedValue({
      T: 8,
      Wt: 14,
      R: 15,
      Wr: 28,
      enforce_weapon_qualification: false,
    });
    vi.mocked(listShifts).mockResolvedValue([
      {
        id: "shift-1",
        duty_type_id: "duty-type-1",
        duty_location_id: "location-1",
        start_date: "2026-09-17",
        end_date: "2026-09-18",
        required_count: 1,
        notes: null,
        assigned_count: 0,
        reserve_assigned_count: 0,
        fill_status: "empty",
        status: "active",
        ineligible_count: 0,
      },
    ]);

    renderForm();

    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: /duty-typ/ })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /duty-typ/ }));
    fireEvent.click(screen.getByRole("button", { name: /algorithm\.run_button/ }));

    await waitFor(() => {
      expect(submitJob).toHaveBeenCalledWith(expect.objectContaining({
        settings: expect.objectContaining({ enforce_weapon_qualification: false }),
      }));
    });
  });
});
