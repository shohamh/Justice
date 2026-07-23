import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import SwapsPage from "./SwapsPage";
import * as assignmentsApi from "../api/assignments";
import * as swapsApi from "../api/swaps";
import * as dutyConfigApi from "../api/dutyConfig";
import * as hierarchyApi from "../api/hierarchy";
import * as soldiersApi from "../api/soldiers";
import { useAuth } from "../auth/AuthContext";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../api/assignments");
vi.mock("../api/swaps");
vi.mock("../api/dutyConfig");
vi.mock("../api/hierarchy");
vi.mock("../api/soldiers");
vi.mock("../auth/AuthContext");
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode | ((openHelp: (tab?: string) => void) => React.ReactNode) }) => (
    <div>{typeof children === "function" ? children(() => {}) : children}</div>
  ),
}));

const duty = {
  assignment_id: "a1",
  soldier_id: "sol-1",
  duty_type_id: "dt1",
  duty_type_name: "שמירה",
  duty_location_id: "loc1",
  start_date: "2026-01-05",
  end_date: "2026-01-05",
  start_time: "08:00",
  end_time: "16:00",
  start_at: "2026-01-05T08:00:00",
  end_at: "2026-01-05T16:00:00",
  shift_id: null,
  is_reserve: false,
} as assignmentsApi.EffectiveDuty;

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SwapsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useAuth).mockReturnValue({
    user: { id: "sol-1", full_name: "A", role: "soldier" },
  } as ReturnType<typeof useAuth>);
  vi.mocked(assignmentsApi.listEffectiveDuties).mockResolvedValue([duty]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
  vi.mocked(hierarchyApi.fetchTree).mockResolvedValue([]);
  vi.mocked(swapsApi.getSwapConfig).mockResolvedValue({
    require_manager_approval: false, require_duty_manager_approval: true, max_specific_targets: 5,
  });
  vi.mocked(swapsApi.listMySwaps).mockResolvedValue([]);
  vi.mocked(swapsApi.listBoard).mockResolvedValue([]);
  vi.mocked(swapsApi.listIncomingSwaps).mockResolvedValue([]);
  vi.mocked(soldiersApi.listSoldiers).mockResolvedValue([]);
  vi.mocked(swapsApi.listEligibleTargets).mockResolvedValue([]);
});

describe("SwapsPage - AskSwapModal eligible-soldier picker", () => {
  it("lists eligible soldiers with hierarchy distance and lets the requester check some", async () => {
    vi.mocked(swapsApi.listEligibleTargets).mockResolvedValue([
      { soldier_id: "sol-2", full_name: "דני כהן", node_name: "מחלקה א", hierarchy_distance: 0 },
      { soldier_id: "sol-3", full_name: "יוסי לוי", node_name: "מחלקה ב", hierarchy_distance: 2 },
    ]);
    renderPage();

    const askButton = await screen.findByText("swaps.ask_swap");
    fireEvent.click(askButton);

    const soldierModeRadio = await screen.findByText("swaps.send_to_soldier");
    fireEvent.click(soldierModeRadio);

    expect(await screen.findByText("דני כהן — מחלקה א (0)")).toBeInTheDocument();
    expect(await screen.findByText("יוסי לוי — מחלקה ב (2)")).toBeInTheDocument();

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
    fireEvent.click(checkboxes[0]);
    expect(checkboxes[0]).toBeChecked();
  });

  it("disables further checkboxes once the max_specific_targets cap is reached", async () => {
    vi.mocked(swapsApi.getSwapConfig).mockResolvedValue({
      require_manager_approval: false, require_duty_manager_approval: true, max_specific_targets: 1,
    });
    vi.mocked(swapsApi.listEligibleTargets).mockResolvedValue([
      { soldier_id: "sol-2", full_name: "דני כהן", node_name: null, hierarchy_distance: 0 },
      { soldier_id: "sol-3", full_name: "יוסי לוי", node_name: null, hierarchy_distance: 1 },
    ]);
    renderPage();

    fireEvent.click(await screen.findByText("swaps.ask_swap"));
    fireEvent.click(await screen.findByText("swaps.send_to_soldier"));

    const checkboxes = await screen.findAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    expect(checkboxes[0]).toBeChecked();
    expect(checkboxes[1]).toBeDisabled();
  });

  it("shows the no-eligible-targets message when the list is empty", async () => {
    vi.mocked(swapsApi.listEligibleTargets).mockResolvedValue([]);
    renderPage();

    fireEvent.click(await screen.findByText("swaps.ask_swap"));
    fireEvent.click(await screen.findByText("swaps.send_to_soldier"));

    expect(await screen.findByText("swaps.no_eligible_targets")).toBeInTheDocument();
  });

  it("submits a bulk swap request with the selected target ids", async () => {
    vi.mocked(swapsApi.listEligibleTargets).mockResolvedValue([
      { soldier_id: "sol-2", full_name: "דני כהן", node_name: null, hierarchy_distance: 0 },
      { soldier_id: "sol-3", full_name: "יוסי לוי", node_name: null, hierarchy_distance: 1 },
    ]);
    vi.mocked(swapsApi.createBulkSwap).mockResolvedValue([]);
    renderPage();

    fireEvent.click(await screen.findByText("swaps.ask_swap"));
    fireEvent.click(await screen.findByText("swaps.send_to_soldier"));

    const checkboxes = await screen.findAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    fireEvent.click(await screen.findByText("swaps.save"));

    await waitFor(() => {
      expect(swapsApi.createBulkSwap).toHaveBeenCalledWith({
        duty_assignment_id: "a1",
        target_soldier_ids: ["sol-2", "sol-3"],
        reason: null,
      });
    });
    expect(swapsApi.createSwap).not.toHaveBeenCalled();
  });

  it("disables save and does not silently post to the open board when soldier mode has zero targets selected", async () => {
    vi.mocked(swapsApi.listEligibleTargets).mockResolvedValue([
      { soldier_id: "sol-2", full_name: "דני כהן", node_name: null, hierarchy_distance: 0 },
    ]);
    renderPage();

    fireEvent.click(await screen.findByText("swaps.ask_swap"));
    fireEvent.click(await screen.findByText("swaps.send_to_soldier"));

    const saveButton = await screen.findByText("swaps.save");
    expect(saveButton).toBeDisabled();

    fireEvent.click(saveButton);

    expect(swapsApi.createBulkSwap).not.toHaveBeenCalled();
    expect(swapsApi.createSwap).not.toHaveBeenCalled();
  });

  it("re-enables save once a target is selected in soldier mode", async () => {
    vi.mocked(swapsApi.listEligibleTargets).mockResolvedValue([
      { soldier_id: "sol-2", full_name: "דני כהן", node_name: null, hierarchy_distance: 0 },
    ]);
    renderPage();

    fireEvent.click(await screen.findByText("swaps.ask_swap"));
    fireEvent.click(await screen.findByText("swaps.send_to_soldier"));

    const saveButton = await screen.findByText("swaps.save");
    expect(saveButton).toBeDisabled();

    const checkbox = await screen.findByRole("checkbox");
    fireEvent.click(checkbox);

    expect(saveButton).not.toBeDisabled();
  });

  it("shows a field list (not the raw English msg) for an array-shaped 422 validation error detail", async () => {
    vi.mocked(swapsApi.createSwap).mockRejectedValue({
      response: { data: { detail: [{ msg: "Input should be a valid date", loc: ["body", "date"], type: "value_error" }] } },
    });
    renderPage();

    const askButton = await screen.findByText("swaps.ask_swap");
    fireEvent.click(askButton);

    const saveButton = await screen.findByText("swaps.save");
    fireEvent.click(saveButton);

    expect(await screen.findByText("נתונים לא תקינים בשדות: date")).toBeInTheDocument();
  });

  it("strips the cover_not_eligible prefix from error messages", async () => {
    vi.mocked(swapsApi.createSwap).mockRejectedValue({
      response: { data: { detail: "cover_not_eligible:פטור מסוג תורנות זו" } },
    });
    renderPage();

    const askButton = await screen.findByText("swaps.ask_swap");
    fireEvent.click(askButton);

    const saveButton = await screen.findByText("swaps.save");
    fireEvent.click(saveButton);

    expect(await screen.findByText("פטור מסוג תורנות זו")).toBeInTheDocument();
  });
});
