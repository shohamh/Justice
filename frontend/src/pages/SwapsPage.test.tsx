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
  vi.mocked(swapsApi.getSwapConfig).mockResolvedValue({ require_manager_approval: false, require_duty_manager_approval: true });
  vi.mocked(swapsApi.listMySwaps).mockResolvedValue([]);
  vi.mocked(swapsApi.listBoard).mockResolvedValue([]);
  vi.mocked(swapsApi.listIncomingSwaps).mockResolvedValue([]);
  vi.mocked(soldiersApi.listSoldiers).mockResolvedValue([]);
});

describe("SwapsPage - AskSwapModal soldier search", () => {
  it("lets the requester pick a soldier via search instead of typing a raw id", async () => {
    renderPage();

    const askButton = await screen.findByText("swaps.ask_swap");
    fireEvent.click(askButton);

    const soldierModeRadio = await screen.findByText("swaps.send_to_soldier");
    fireEvent.click(soldierModeRadio);

    expect(await screen.findByTestId("soldier-search-input")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("מספר אישי של חייל")).not.toBeInTheDocument();
  });

  it("does not offer a dead create-new-soldier option in the swap target search", async () => {
    vi.mocked(soldiersApi.listSoldiers).mockResolvedValue([
      {
        id: "sol-2",
        personal_number: "1234567",
        full_name: "דני כהן",
        role: "soldier",
        hierarchy_node_id: null,
        phone: null,
        must_change_password: false,
        left_at: null,
      } as soldiersApi.SoldierDTO,
    ]);
    renderPage();

    const askButton = await screen.findByText("swaps.ask_swap");
    fireEvent.click(askButton);
    fireEvent.click(await screen.findByText("swaps.send_to_soldier"));

    const input = await screen.findByTestId("soldier-search-input");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "דני" } });

    await screen.findByTestId("soldier-search-dropdown");
    expect(screen.queryByTestId("soldier-search-create-new")).not.toBeInTheDocument();

    // Also true for a query that matches nothing in the directory.
    fireEvent.change(input, { target: { value: "לא קיים בכלל" } });
    await waitFor(() => {
      expect(screen.queryByTestId("soldier-search-create-new")).not.toBeInTheDocument();
    });
  });

  it("extracts a message from an array-shaped 422 validation error detail", async () => {
    vi.mocked(swapsApi.createSwap).mockRejectedValue({
      response: { data: { detail: [{ msg: "תאריך לא תקין", loc: ["body", "date"], type: "value_error" }] } },
    });
    renderPage();

    const askButton = await screen.findByText("swaps.ask_swap");
    fireEvent.click(askButton);

    const saveButton = await screen.findByText("swaps.save");
    fireEvent.click(saveButton);

    expect(await screen.findByText("תאריך לא תקין")).toBeInTheDocument();
  });
});
