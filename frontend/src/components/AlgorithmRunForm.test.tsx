import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import AlgorithmRunForm from "./AlgorithmRunForm";
import { getAlgorithmDefaults } from "../api/algorithm";
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
    vi.mocked(getAlgorithmDefaults).mockResolvedValue({ T: 5, Wt: 10, R: 12, Wr: 20 });

    render(<AlgorithmRunForm dutyTypes={[]} onJobSubmitted={vi.fn()} />);

    await waitFor(() => {
      expect(getAlgorithmDefaults).toHaveBeenCalled();
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
