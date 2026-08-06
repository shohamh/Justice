import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, test, vi, beforeEach } from "vitest";
import AskSwapModal from "./AskSwapModal";

const mockCreateSwap = vi.fn().mockResolvedValue({});
const mockAddSwapTargets = vi.fn().mockResolvedValue({});
const mockPublishSwapToMarketplace = vi.fn().mockResolvedValue({});
const mockListEligibleTargets = vi.fn().mockResolvedValue([{ soldier_id: "s1", full_name: "Yossi", node_name: null, hierarchy_distance: 1 }]);
const mockGetSwapConfig = vi.fn().mockResolvedValue({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 5 });
vi.mock("../api/swaps", () => ({
  createSwap: (...args: unknown[]) => mockCreateSwap(...args),
  addSwapTargets: (...args: unknown[]) => mockAddSwapTargets(...args),
  publishSwapToMarketplace: (...args: unknown[]) => mockPublishSwapToMarketplace(...args),
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

  test("shows a loading message instead of the empty state while eligible targets are still loading", async () => {
    let resolveTargets!: (v: unknown[]) => void;
    mockListEligibleTargets.mockReturnValueOnce(new Promise((resolve) => { resolveTargets = resolve; }));
    renderModal();
    expect(screen.getByText("swaps.loading_eligible_targets")).toBeInTheDocument();
    expect(screen.queryByText("swaps.no_eligible_targets")).not.toBeInTheDocument();
    resolveTargets([]);
    expect(await screen.findByText("swaps.no_eligible_targets")).toBeInTheDocument();
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

  function renderEditModal(editingSwap: { id: string; open_to_marketplace: boolean; candidates: { soldier_id: string }[] }) {
    const client = new QueryClient();
    return render(
      <QueryClientProvider client={client}>
        <AskSwapModal
          duty={{ assignment_id: "a1", start_date: "2026-08-01", end_date: "2026-08-02" } as never}
          dutyTypeName="Guard"
          editingSwap={editingSwap}
          onClose={vi.fn()}
          onCreated={vi.fn()}
        />
      </QueryClientProvider>,
    );
  }

  test("edit mode: an already-invited person's checkbox is disabled with an explanation", async () => {
    renderEditModal({ id: "req1", open_to_marketplace: false, candidates: [{ soldier_id: "s1" }] });
    await waitFor(() => expect(screen.getAllByRole("checkbox")).toHaveLength(2));
    const checkbox = screen.getAllByRole("checkbox")[1];
    expect(checkbox).toBeDisabled();
    expect(await screen.findByText("swaps.already_invited")).toBeInTheDocument();
  });

  test("edit mode: an already-published marketplace checkbox is checked, disabled, with an explanation", async () => {
    renderEditModal({ id: "req1", open_to_marketplace: true, candidates: [] });
    const marketplaceCheckbox = await screen.findByTestId("ask-swap-marketplace-checkbox");
    expect(marketplaceCheckbox).toBeChecked();
    expect(marketplaceCheckbox).toBeDisabled();
    expect(await screen.findByText("swaps.already_on_marketplace")).toBeInTheDocument();
  });

  test("edit mode: submit only calls addSwapTargets for newly selected people", async () => {
    mockAddSwapTargets.mockClear();
    mockPublishSwapToMarketplace.mockClear();
    renderEditModal({ id: "req1", open_to_marketplace: false, candidates: [] });
    await waitFor(() => expect(screen.getAllByRole("checkbox")).toHaveLength(2));
    const targetCheckbox = screen.getAllByRole("checkbox")[1];
    fireEvent.click(targetCheckbox);
    fireEvent.click(screen.getByText("swaps.save"));
    await waitFor(() => expect(mockAddSwapTargets).toHaveBeenCalledWith("req1", ["s1"]));
    expect(mockPublishSwapToMarketplace).not.toHaveBeenCalled();
  });

  test("edit mode: submit only calls publishSwapToMarketplace when the marketplace box is newly checked", async () => {
    mockAddSwapTargets.mockClear();
    mockPublishSwapToMarketplace.mockClear();
    renderEditModal({ id: "req1", open_to_marketplace: false, candidates: [] });
    fireEvent.click(await screen.findByTestId("ask-swap-marketplace-checkbox"));
    fireEvent.click(screen.getByText("swaps.save"));
    await waitFor(() => expect(mockPublishSwapToMarketplace).toHaveBeenCalledWith("req1"));
    expect(mockAddSwapTargets).not.toHaveBeenCalled();
  });

  test("edit mode: submit is disabled when nothing new is selected", async () => {
    renderEditModal({ id: "req1", open_to_marketplace: true, candidates: [{ soldier_id: "s1" }] });
    await screen.findAllByRole("checkbox");
    expect(screen.getByText("swaps.save")).toBeDisabled();
  });

  test("filters the target list by a search query", async () => {
    mockListEligibleTargets.mockResolvedValueOnce([
      { soldier_id: "s1", full_name: "Yossi Cohen", node_name: null, hierarchy_distance: 1 },
      { soldier_id: "s2", full_name: "Dana Levi", node_name: null, hierarchy_distance: 1 },
    ]);
    renderModal();
    expect(await screen.findByText(/Yossi Cohen/)).toBeInTheDocument();
    expect(screen.getByText(/Dana Levi/)).toBeInTheDocument();
    const searchInput = screen.getByTestId("ask-swap-target-search");
    fireEvent.change(searchInput, { target: { value: "Dana" } });
    await waitFor(() => expect(screen.queryByText(/Yossi Cohen/)).not.toBeInTheDocument());
    expect(screen.getByText(/Dana Levi/)).toBeInTheDocument();
  });

  test("shows a distinct no-results message (not the no-eligible-targets message) when a search query matches nobody", async () => {
    mockListEligibleTargets.mockResolvedValueOnce([
      { soldier_id: "s1", full_name: "Yossi Cohen", node_name: null, hierarchy_distance: 1 },
    ]);
    renderModal();
    expect(await screen.findByText(/Yossi Cohen/)).toBeInTheDocument();
    const searchInput = screen.getByTestId("ask-swap-target-search");
    fireEvent.change(searchInput, { target: { value: "Zzzzz nonexistent" } });
    await waitFor(() => expect(screen.getByText("swaps.no_search_results")).toBeInTheDocument());
    expect(screen.queryByText("swaps.no_eligible_targets")).not.toBeInTheDocument();
  });

  test("edit mode: eligible people grey out with invite_limit_reached once existing candidates already fill the cap", async () => {
    mockGetSwapConfig.mockResolvedValueOnce({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 2 });
    mockListEligibleTargets.mockResolvedValueOnce([
      { soldier_id: "s1", full_name: "Yossi", node_name: null, hierarchy_distance: 1 },
      { soldier_id: "s2", full_name: "Dana", node_name: null, hierarchy_distance: 1 },
    ]);
    renderEditModal({ id: "req1", open_to_marketplace: false, candidates: [{ soldier_id: "existing1" }, { soldier_id: "existing2" }] });
    await waitFor(() => expect(screen.getAllByRole("checkbox")).toHaveLength(3));
    const targetCheckbox = screen.getAllByRole("checkbox")[1]; // s1, not already invited
    expect(targetCheckbox).toBeDisabled();
    expect((await screen.findAllByText("swaps.invite_limit_reached")).length).toBeGreaterThan(0);
  });
});
