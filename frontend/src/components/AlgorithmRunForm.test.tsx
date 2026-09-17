import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import AlgorithmRunForm from "./AlgorithmRunForm";
import { checkAvailability, getAlgorithmDefaults, submitJob } from "../api/algorithm";
import { listShifts } from "../api/shifts";
import { fetchTree } from "../api/hierarchy";

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
  fetchTree: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listShifts).mockResolvedValue([]);
  vi.mocked(fetchTree).mockResolvedValue([]);
  vi.mocked(checkAvailability).mockResolvedValue({ has_shortage: false, items: [] });
  vi.mocked(submitJob).mockResolvedValue({ id: "job-1", status: "pending" });
});

describe("AlgorithmRunForm - defaults load failure", () => {
  it("surfaces a load error and keeps the hardcoded fallback settings when defaults fail to load", async () => {
    vi.mocked(getAlgorithmDefaults).mockRejectedValue(new Error("Invalid algorithm defaults response"));

    render(<AlgorithmRunForm dutyTypes={[]} onJobSubmitted={vi.fn()} />);

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

    render(<AlgorithmRunForm dutyTypes={[]} onJobSubmitted={vi.fn()} />);

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

    render(<AlgorithmRunForm dutyTypes={[]} onJobSubmitted={vi.fn()} />);

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
