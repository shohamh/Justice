import { render, screen, fireEvent } from "@testing-library/react";
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
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
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
  vi.mocked(swapsApi.getSwapConfig).mockResolvedValue({ require_manager_approval: false });
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
});
