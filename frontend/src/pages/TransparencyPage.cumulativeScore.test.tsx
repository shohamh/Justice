import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import "../i18n";
import TransparencyPage from "./TransparencyPage";
import * as scoringApi from "../api/scoring";
import * as hierarchyApi from "../api/hierarchy";
import * as potentialApi from "../api/potential";
import type { TransparencyOut, TransparencyRow } from "../api/scoring";

vi.mock("../api/scoring");
vi.mock("../api/hierarchy");
vi.mock("../api/potential");

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../components/CursorPagedTable", () => ({
  default: ({ columns }: {
    columns: Array<{ id: string; cell: (row: TransparencyRow) => ReactNode }>;
  }) => {
    const cumulative = columns.find((column) => column.id === "cumulative");
    return <div>{cumulative?.cell(makeRow())}</div>;
  },
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "viewer-1",
      role: "admin",
      hierarchy_node_id: null,
      scope_root_ids: [],
      active_deputy_grants: [],
      is_commander: false,
      is_duty_manager: false,
      can_view_transparency: true,
    },
    authScopeReady: true,
    refreshMe: vi.fn(),
  }),
}));

const mockOpenSoldierModal = vi.fn();
vi.mock("../contexts/SoldierModalContext", () => ({
  useSoldierModal: () => ({ openSoldierModal: mockOpenSoldierModal }),
}));

function makeRow(overrides: Partial<TransparencyRow> = {}): TransparencyRow {
  return {
    soldier_id: "s1",
    full_name: "חייל בדיקה",
    node_id: "node-1",
    node_name: "יחידה 1",
    enrolled_at: "2026-01-01",
    active_days: 10,
    shift_count: 2,
    rank: null,
    is_officer: false,
    service_type: "חובה",
    cumulative_score: "1.00",
    score_per_day: "0.10",
    normalised_score: "1.00",
    is_globally_exempted: false,
    burden_share: 0.1,
    c_over_d: 0,
    burden_share_offset_raw: 0,
    exemptions_display: "",
    exemptions_visible: true,
    exemptions: [],
    has_global_exemption: false,
    has_partial_exemption: false,
    has_temporary_exemption: false,
    ...overrides,
  };
}

beforeEach(() => {
  mockOpenSoldierModal.mockReset();
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(scoringApi.getFairnessComponents).mockRejectedValue(new Error("not needed"));
  vi.mocked(potentialApi.getBurdenShareGap).mockResolvedValue([]);
});

describe("TransparencyPage cumulative score button", () => {
  it("opens the soldier modal on the duty_history tab, filtered to score-affecting event types", async () => {
    const out: TransparencyOut = {
      rows: [makeRow()],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);
    vi.mocked(scoringApi.getFairnessComponents).mockImplementation(() => new Promise(() => {}));

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter><TransparencyPage /></MemoryRouter>
      </QueryClientProvider>,
    );

    const scoreButton = await screen.findByTestId("transparency-cumulative-score-s1");
    fireEvent.click(scoreButton);
    await waitFor(() => expect(mockOpenSoldierModal).toHaveBeenCalledWith(
      "s1",
      undefined,
      "duty_history",
      ["assignment", "cancellation", "call_up", "dismissal"],
    ));
  });
});
