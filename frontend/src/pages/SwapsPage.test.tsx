import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, test, vi } from "vitest";
import SwapsPage from "./SwapsPage";
import type { SwapRequest } from "../api/swaps";

const { mySwap } = vi.hoisted(() => {
  const mySwap: SwapRequest = {
    id: "req1", duty_assignment_id: "a1", duty_date: "2026-08-01", requesting_soldier_id: "me",
    open_to_marketplace: true, status: "open", reason: null, requester_side_approved: true,
    decision_note: null, created_at: "2026-07-01T00:00:00Z",
    duty_type_name: "Guard", duty_location_name: "Base", duty_type_id: "dt1", duty_location_id: "l1",
    duty_start_date: "2026-08-01", duty_end_date: "2026-08-02", duty_shift_id: null,
    requesting_soldier_name: "Me", requesting_commander_name: null, requesting_soldier_node_name: null,
    requester_manager_approvals: [],
    candidates: [
      { id: "c1", soldier_id: "s1", soldier_name: "Yossi", source: "invited", status: "pending", soldier_side_approved: null, offered_assignment_ids: [], manager_approvals: [] },
      { id: "c2", soldier_id: "s2", soldier_name: "Dana", source: "marketplace", status: "accepted", soldier_side_approved: true, offered_assignment_ids: [], manager_approvals: [] },
    ],
  };
  return { mySwap };
});

vi.mock("../api/swaps", async () => {
  const actual = await vi.importActual<typeof import("../api/swaps")>("../api/swaps");
  return {
    ...actual,
    listMySwaps: vi.fn().mockResolvedValue([mySwap]),
    listBoard: vi.fn().mockResolvedValue([]),
    listIncomingSwaps: vi.fn().mockResolvedValue([]),
    getSwapConfig: vi.fn().mockResolvedValue({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 5 }),
  };
});
vi.mock("../api/assignments", () => ({ listEffectiveDuties: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/dutyConfig", () => ({ listDutyTypes: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/hierarchy", () => ({ fetchTree: vi.fn().mockResolvedValue([]) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { id: "me", role: "soldier", is_commander: false, is_duty_manager: false } }) }));
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode | ((openHelp: (tab?: string) => void) => React.ReactNode) }) => (
    <div>{typeof children === "function" ? children(() => {}) : children}</div>
  ),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SwapsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SwapsPage mine tab candidate list", () => {
  test("shows one card per request with both candidates listed, not one card per candidate", async () => {
    renderPage();
    expect(await screen.findByText("Yossi")).toBeInTheDocument();
    expect(await screen.findByText("Dana")).toBeInTheDocument();
    // Exactly one duty header/date rendered for this request, proving it's
    // one card, not two — SwapDutyHeader renders the duty_type_name once per card.
    expect(screen.getAllByText("Guard")).toHaveLength(1);
  });
});
