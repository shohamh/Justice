import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CommandDashboardPage from "./CommandDashboardPage";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "commander-1", is_commander: true, role: "commander" } }),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../components/Layout", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../components/UpcomingSnapshot", () => ({ default: () => <div data-testid="upcoming-snapshot" /> }));
vi.mock("../components/AlertsPanel", () => ({ default: () => <div data-testid="alerts-panel" /> }));
vi.mock("../components/DutyPotentialPanel", () => ({ default: () => <div data-testid="duty-potential" /> }));
vi.mock("../components/dashboard/PendingApprovalsWidget", () => ({ default: () => <div data-testid="pending-approvals" /> }));
vi.mock("../components/UnitCalendar", () => ({ default: () => <div data-testid="unit-calendar" /> }));
vi.mock("../components/HierarchyTree", () => ({ default: () => <div data-testid="hierarchy-tree" /> }));
vi.mock("../hooks/useLevelTypes", () => ({ useLevelTypes: () => ({ levelTypes: [] }) }));
vi.mock("../api/commanderDashboard", () => ({
  getSummary: vi.fn().mockResolvedValue({}),
  getPotential: vi.fn().mockResolvedValue(null),
  getUpcoming: vi.fn().mockResolvedValue(null),
  getAlerts: vi.fn().mockResolvedValue([]),
}));
vi.mock("../api/hierarchy", () => ({ fetchFullTree: vi.fn().mockResolvedValue([{ id: "node-1", name: "Unit", commander_id: "commander-1" }]) }));
vi.mock("../api/enrollment", () => ({ listPendingEnrollments: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/swaps", () => ({ listPendingSwaps: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/constraints", () => ({ getPendingCount: vi.fn().mockResolvedValue(0) }));
vi.mock("../api/exemptions", () => ({ getPendingExemptionCount: vi.fn().mockResolvedValue(0) }));
vi.mock("../api/soldiers", () => ({ getPendingFieldUpdateCount: vi.fn().mockResolvedValue(0) }));
vi.mock("../api/hierarchyTransfers", () => ({ listPendingTransferRequests: vi.fn().mockResolvedValue([]) }));
vi.mock("../api/ineligibleSoldiers", () => ({ getIneligibleSoldiers: vi.fn().mockResolvedValue([]) }));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<MemoryRouter><QueryClientProvider client={queryClient}><CommandDashboardPage /></QueryClientProvider></MemoryRouter>);
}

beforeEach(() => vi.clearAllMocks());

describe("CommandDashboardPage", () => {
  it("does not render redundant soldiers, entries/exits, or fairness panels", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("panel-calendar")).toBeInTheDocument());
    expect(screen.queryByTestId("panel-soldiers")).not.toBeInTheDocument();
    expect(screen.queryByTestId("panel-entries_exits")).not.toBeInTheDocument();
    expect(screen.queryByTestId("panel-fairness_internal")).not.toBeInTheDocument();
    expect(screen.queryByTestId("panel-fairness_external")).not.toBeInTheDocument();
  });
});
