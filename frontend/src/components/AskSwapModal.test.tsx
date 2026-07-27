import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, test, vi, beforeEach } from "vitest";
import AskSwapModal from "./AskSwapModal";

const mockCreateSwap = vi.fn().mockResolvedValue({});
const mockListEligibleTargets = vi.fn().mockResolvedValue([{ soldier_id: "s1", full_name: "Yossi", node_name: null, hierarchy_distance: 1 }]);
const mockGetSwapConfig = vi.fn().mockResolvedValue({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 5 });
vi.mock("../api/swaps", () => ({
  createSwap: (...args: unknown[]) => mockCreateSwap(...args),
  listEligibleTargets: (...args: unknown[]) => mockListEligibleTargets(...args),
  getSwapConfig: (...args: unknown[]) => mockGetSwapConfig(...args),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ enrollmentPending: false }) }));

function renderModal() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <AskSwapModal
        duty={{ assignment_id: "a1", start_date: "2026-08-01", end_date: "2026-08-02" } as never}
        dutyTypeName="Guard"
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("AskSwapModal", () => {
  beforeEach(() => mockCreateSwap.mockClear());

  test("submitting with the marketplace checkbox AND a selected target sends both in one call", async () => {
    renderModal();
    fireEvent.click(await screen.findByTestId("ask-swap-marketplace-checkbox"));
    const targetCheckbox = (await screen.findAllByRole("checkbox"))[1];
    fireEvent.click(targetCheckbox);
    fireEvent.click(screen.getByText("swaps.save"));
    await waitFor(() => expect(mockCreateSwap).toHaveBeenCalledWith(
      expect.objectContaining({ open_to_marketplace: true, target_soldier_ids: ["s1"] }),
    ));
  });

  test("submit is disabled with neither marketplace checked nor a target selected", () => {
    renderModal();
    expect(screen.getByText("swaps.save")).toBeDisabled();
  });

  test("shows a field list (not the raw English msg) for an array-shaped 422 validation error detail", async () => {
    mockCreateSwap.mockRejectedValueOnce({
      response: { data: { detail: [{ msg: "Input should be a valid date", loc: ["body", "date"], type: "value_error" }] } },
    });
    renderModal();
    fireEvent.click(await screen.findByTestId("ask-swap-marketplace-checkbox"));
    fireEvent.click(screen.getByText("swaps.save"));
    expect(await screen.findByText("נתונים לא תקינים בשדות: date")).toBeInTheDocument();
  });

  test("strips the cover_not_eligible prefix from error messages", async () => {
    mockCreateSwap.mockRejectedValueOnce({
      response: { data: { detail: "cover_not_eligible:פטור מסוג תורנות זו" } },
    });
    renderModal();
    fireEvent.click(await screen.findByTestId("ask-swap-marketplace-checkbox"));
    fireEvent.click(screen.getByText("swaps.save"));
    expect(await screen.findByText("פטור מסוג תורנות זו")).toBeInTheDocument();
  });

  test("disables further target selection once max_specific_targets is reached", async () => {
    mockGetSwapConfig.mockResolvedValueOnce({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 2 });
    mockListEligibleTargets.mockResolvedValueOnce([
      { soldier_id: "s1", full_name: "Yossi", node_name: null, hierarchy_distance: 1 },
      { soldier_id: "s2", full_name: "Dana", node_name: null, hierarchy_distance: 1 },
      { soldier_id: "s3", full_name: "Roi", node_name: null, hierarchy_distance: 1 },
    ]);
    renderModal();
    await waitFor(() => expect(screen.getAllByRole("checkbox")).toHaveLength(4));
    // index 0 is the marketplace checkbox; 1-3 are the target picker
    const targetCheckboxes = screen.getAllByRole("checkbox");
    fireEvent.click(targetCheckboxes[1]);
    fireEvent.click(targetCheckboxes[2]);
    expect(screen.getAllByRole("checkbox")[1]).not.toBeDisabled();
    expect(screen.getAllByRole("checkbox")[2]).not.toBeDisabled();
    expect(screen.getAllByRole("checkbox")[3]).toBeDisabled();
  });
});
