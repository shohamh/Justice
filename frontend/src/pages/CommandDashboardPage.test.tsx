import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CommandDashboardPage from "./CommandDashboardPage";
import SummaryCards from "../components/SummaryCards";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "commander-1", is_commander: true, role: "commander" } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => ({
      "command_dashboard.title": "דשבורד מפקד",
      "command_dashboard.alerts": "התראות",
      "command_dashboard.approvals": "אישורים",
      "command_dashboard.upcoming": "קרוב",
      "command_dashboard.calendar": "יומן",
      "command_dashboard.soldiers": "חיילים",
      "command_dashboard.soldiers_panel_title": "רשימת חיילים",
      "command_dashboard.soldiers_count": "{{count}} חיילים בפיקוד",
      "command_dashboard.go_to_team": "מעבר לניהול הצוות",
      "command_dashboard.entries_exits": "כניסות ויציאות",
      "command_dashboard.internal_fairness": "הוגנות פנימית",
      "command_dashboard.external_fairness": "הוגנות חיצונית",
      "command_dashboard.potential": "פוטנציאל",
      "command_dashboard.own_potential": "פוטנציאל בפיקוד",
      "command_dashboard.no_own_potential": "אין יחידות תחת פיקודך",
      "command_dashboard.node": "יחידה",
      "command_dashboard.eligible": "זכאים",
      "command_dashboard.modifiers": "מתאמים",
      "command_dashboard.final_potential": "פוטנציאל סופי",
      "range_qualification.dashboard.title": "חיילים ללא כשירות מטווח",
      "range_qualification.soldiersError": "טעינת החיילים ללא הסמכה נכשלה",
    }[key] ?? key),
  }),
}));

vi.mock("../components/Layout", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/UpcomingSnapshot", () => ({ default: () => <div data-testid="upcoming-snapshot" /> }));
vi.mock("../components/AlertsPanel", () => ({ default: () => <div data-testid="alerts-panel" /> }));
vi.mock("../components/FairnessChart", () => ({
  InternalFairness: () => <div data-testid="internal-fairness" />,
  ExternalFairness: () => <div data-testid="external-fairness" />,
}));
vi.mock("../components/DutyPotentialPanel", () => ({ default: () => <div data-testid="duty-potential" /> }));
vi.mock("../components/dashboard/PendingApprovalsWidget", () => ({ default: () => <div data-testid="pending-approvals" /> }));
vi.mock("../components/EntriesExitsPanel", () => ({ default: () => <div data-testid="entries-exits-panel" /> }));
vi.mock("../components/UnitCalendar", () => ({ default: () => <div data-testid="unit-calendar" /> }));
vi.mock("../components/HierarchyTree", () => ({ default: () => <div data-testid="hierarchy-tree" /> }));
vi.mock("../hooks/useLevelTypes", () => ({ useLevelTypes: () => ({ levelTypes: [] }) }));

vi.mock("../api/commanderDashboard", () => ({
  getSummary: vi.fn().mockResolvedValue({}),
  getDashboardSoldiers: vi.fn().mockResolvedValue([
    { id: "sol-1", personal_number: "1", full_name: "א", role: "soldier", hierarchy_node_id: "node-1", status: "active", cumulative_score: "0", normalised_score: "0", enrolled_at: "2026-01-01", left_at: null },
  ]),
  getFairnessInternal: vi.fn().mockResolvedValue(null), getFairnessExternal: vi.fn().mockResolvedValue(null),
  getPotential: vi.fn().mockResolvedValue(null), getUpcoming: vi.fn().mockResolvedValue(null), getAlerts: vi.fn().mockResolvedValue([]),
}));
vi.mock("../api/hierarchy", () => ({ fetchFullTree: vi.fn().mockResolvedValue([{ id: "node-1", name: "פלוגה א", commander_id: "commander-1" }]) }));
vi.mock("../api/soldiers", () => ({ listSoldiers: vi.fn().mockResolvedValue([]), getPendingFieldUpdateCount: vi.fn().mockResolvedValue(0) }));
vi.mock("../api/potential", () => ({ getPotential: vi.fn().mockResolvedValue({ raw_eligible_count: 0, modifiers: [], final_potential: 0 }) }));
vi.mock("../api/enrollment", () => ({ listPendingEnrollments: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/swaps", () => ({ listPendingSwaps: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/constraints", () => ({ getPendingCount: vi.fn().mockResolvedValue(0) }));
vi.mock("../api/exemptions", () => ({ getPendingExemptionCount: vi.fn().mockResolvedValue(0) }));
vi.mock("../api/ineligibleSoldiers", () => ({ getIneligibleSoldiers: vi.fn() }));

import { getIneligibleSoldiers } from "../api/ineligibleSoldiers";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}><CommandDashboardPage /></QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("CommandDashboardPage", () => {
  it("keeps unrelated dashboard panels available when the commander eligibility query fails", async () => {
    vi.mocked(getIneligibleSoldiers).mockRejectedValue(new Error("boom"));
    renderPage();

    await waitFor(() => expect(getIneligibleSoldiers).toHaveBeenCalledWith("commander"));
    expect(screen.getByTestId("panel-ineligible-soldiers")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("טעינת החיילים ללא הסמכה נכשלה");
    expect(screen.getByTestId("alerts-panel")).toBeInTheDocument();
    expect(screen.getByTestId("pending-approvals")).toBeInTheDocument();
  });

  it("shows a read-only soldier-count summary and a link to /team instead of the full hierarchy tree", async () => {
    renderPage();

    const panel = await screen.findByTestId("panel-soldiers");
    expect(within(panel).queryByTestId("hierarchy-tree")).not.toBeInTheDocument();
    expect(within(panel).getByTestId("soldiers-summary")).toBeInTheDocument();
    const link = within(panel).getByTestId("soldiers-panel-team-link");
    expect(link).toHaveAttribute("href", "/team");
  });
});

describe("SummaryCards", () => {
  it("renders without an onCardClick prop", () => {
    render(<SummaryCards data={{ approvals_pending: 1, upcoming_duties_7d: 2, unfilled_gaps: 0, alerts_count: 0 }} />);
    expect(screen.getByTestId("summary-cards")).toBeInTheDocument();
  });
});
