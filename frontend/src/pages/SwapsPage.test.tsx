import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, test, vi } from "vitest";
import SwapsPage from "./SwapsPage";
import type { SwapRequest } from "../api/swaps";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";

const { mySwap, incomingSwap } = vi.hoisted(() => {
  const mySwap: SwapRequest = {
    id: "req1", duty_assignment_id: "a1", duty_date: "2026-08-01", requesting_soldier_id: "me",
    open_to_marketplace: true, status: "open", reason: "אירוע משפחתי", requester_side_approved: true,
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
  const incomingSwap: SwapRequest = {
    id: "req2", duty_assignment_id: "a2", duty_date: "2026-08-05", requesting_soldier_id: "other",
    open_to_marketplace: false, status: "open", reason: null, requester_side_approved: true,
    decision_note: null, created_at: "2026-07-01T00:00:00Z",
    duty_type_name: "Patrol", duty_location_name: "Base", duty_type_id: "dt2", duty_location_id: "l1",
    duty_start_date: "2026-08-05", duty_end_date: "2026-08-06", duty_shift_id: null,
    requesting_soldier_name: "Other", requesting_commander_name: null, requesting_soldier_node_name: null,
    requester_manager_approvals: [],
    // "me" is the invited candidate on this request.
    candidates: [
      { id: "c3", soldier_id: "me", soldier_name: "Me", source: "invited", status: "pending", soldier_side_approved: null, offered_assignment_ids: [], manager_approvals: [] },
    ],
  };
  return { mySwap, incomingSwap };
});

vi.mock("../api/swaps", async () => {
  const actual = await vi.importActual<typeof import("../api/swaps")>("../api/swaps");
  return {
    ...actual,
    listMySwaps: vi.fn().mockResolvedValue([mySwap]),
    listBoard: vi.fn().mockResolvedValue([]),
    listIncomingSwaps: vi.fn().mockResolvedValue([incomingSwap]),
    getSwapConfig: vi.fn().mockResolvedValue({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 5 }),
    checkCoverEligibility: vi.fn().mockResolvedValue({ eligible: true, reason: null }),
    listEligibleTargets: vi.fn().mockResolvedValue([]),
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

function renderPage(initialEntries = ["/swaps"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SoldierModalProvider>
        <MemoryRouter initialEntries={initialEntries}>
          <SwapsPage />
        </MemoryRouter>
      </SoldierModalProvider>
    </QueryClientProvider>,
  );
}

describe("SwapsPage mine tab candidate list", () => {
  test("shows one card per request with both candidates listed, not one card per candidate", async () => {
    renderPage();
    // Each live candidate's name renders twice by design — once as their
    // SwapApprovalColumns column label, once in their CandidateRow entry
    // (which no longer hides the name for live candidates, since the
    // column can scroll out of view on narrow viewports).
    expect(await screen.findAllByText("Yossi")).toHaveLength(2);
    expect(screen.getAllByText("Dana")).toHaveLength(2);
    // Exactly one duty header/date rendered for this request, proving it's
    // one card, not two — SwapDutyHeader renders the duty_type_name once per card.
    expect(screen.getAllByText("Guard")).toHaveLength(1);
  });

  test("shows a Manage button on an open request that opens the edit modal", async () => {
    renderPage();
    const manageButton = await screen.findByText("swaps.manage_button");
    fireEvent.click(manageButton);
    expect(await screen.findByText("swaps.manage_swap_title: Guard")).toBeInTheDocument();
  });
});

describe("SwapsPage incoming tab", () => {
  test("shows only the dedicated approve/reject controls for an invited candidate, not the marketplace cover button too", async () => {
    renderPage(["/swaps?tab=incoming"]);
    // Approve/reject controls for the invite render.
    expect(await screen.findByText("approvals.approve")).toBeInTheDocument();
    expect(screen.getByText("approvals.reject")).toBeInTheDocument();
    // The marketplace-claim button must NOT also render — an invited
    // candidate shouldn't be offered two overlapping ways to respond.
    expect(screen.queryByText("swaps.accept_cover")).not.toBeInTheDocument();
  });
});

describe("SwapsPage reason label", () => {
  test("prefixes the swap reason with a label instead of showing bare text", async () => {
    renderPage();
    expect(await screen.findByText("swaps.reason: אירוע משפחתי")).toBeInTheDocument();
  });
});

describe("SwapsPage incoming tab approval columns", () => {
  test("shows a two-column approval block for an incoming swap, mine first", async () => {
    const { getSwapConfig, listIncomingSwaps } = await import("../api/swaps");
    vi.mocked(listIncomingSwaps).mockResolvedValueOnce([
      {
        id: "req2", duty_assignment_id: "a2", duty_date: "2026-08-05", requesting_soldier_id: "other",
        open_to_marketplace: true, status: "open", reason: null, requester_side_approved: null,
        decision_note: null, created_at: "2026-07-01T00:00:00Z",
        duty_type_name: "Patrol", duty_location_name: "North", duty_type_id: "dt2", duty_location_id: "l2",
        duty_start_date: "2026-08-05", duty_end_date: "2026-08-06", duty_shift_id: null,
        requesting_soldier_name: "Other", requesting_commander_name: null, requesting_soldier_node_name: null,
        requester_manager_approvals: [],
        candidates: [
          { id: "c3", soldier_id: "me", soldier_name: "Me", source: "invited", status: "pending", soldier_side_approved: null, offered_assignment_ids: [], manager_approvals: [] },
        ],
      },
    ]);
    vi.mocked(getSwapConfig).mockResolvedValueOnce({ require_manager_approval: true, require_duty_manager_approval: true, max_specific_targets: 5 });
    renderPage(["/swaps?tab=incoming"]);
    const meLabel = await screen.findByText("swaps.covering");
    const requesterLabel = screen.getByText("Other");
    // "Me" column must come before the requester column in DOM order (right-first in RTL).
    expect(meLabel.compareDocumentPosition(requesterLabel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("SwapsPage duties query", () => {
  test("fetches effective duties with for_swap so drafts and received duties are listed", async () => {
    const { listEffectiveDuties } = await import("../api/assignments");
    renderPage();
    await screen.findAllByText("Yossi");
    expect(listEffectiveDuties).toHaveBeenCalledWith("me", { for_swap: true });
  });
});
