import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";

import HomePage from "./HomePage";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";
import * as assignmentsApi from "../api/assignments";
import * as dutyConfigApi from "../api/dutyConfig";
import * as swapsApi from "../api/swaps";
import * as enrollmentApi from "../api/enrollment";
import * as systemSettingsApi from "../api/systemSettings";
import * as scoringApi from "../api/scoring";
import * as constraintsApi from "../api/constraints";
import * as exemptionsApi from "../api/exemptions";
import * as soldiersApi from "../api/soldiers";
import * as rangesApi from "../api/ranges";
import * as hierarchyTransfersApi from "../api/hierarchyTransfers";
import * as publicSettingsApi from "../api/publicSettings";
import * as commandDashboardApi from "../api/commanderDashboard";
import * as hierarchyApi from "../api/hierarchy";
import * as potentialApi from "../api/potential";
import * as ineligibleSoldiersApi from "../api/ineligibleSoldiers";
import * as levelTypesApi from "../api/levelTypes";
import type { PermissionUser } from "../auth/permissions";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      (options?.defaultValue as string | undefined) ?? key,
  }),
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("../api/assignments");
vi.mock("../api/dutyConfig");
vi.mock("../api/swaps");
vi.mock("../api/enrollment");
vi.mock("../api/systemSettings");
vi.mock("../api/scoring");
vi.mock("../api/constraints");
vi.mock("../api/exemptions");
vi.mock("../api/soldiers");
vi.mock("../api/ranges");
vi.mock("../api/hierarchyTransfers");
vi.mock("../api/publicSettings");
vi.mock("../api/commanderDashboard");
vi.mock("../api/hierarchy");
vi.mock("../api/potential");
vi.mock("../api/ineligibleSoldiers");
vi.mock("../api/levelTypes");
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const mockUser: PermissionUser = {
  id: "soldier-1",
  full_name: "חייל בדיקה",
  role: "soldier",
  hierarchy_node_id: null,
  is_commander: false,
  is_duty_manager: false,
};

vi.mock("../components/UnitCalendar", () => ({
  default: ({ nodeIds, soldierId, scope, highlightSoldierId }: { nodeIds?: string[]; soldierId?: string; scope?: string; highlightSoldierId?: string }) => (
    <div
      data-testid={nodeIds ? "command-unit-calendar" : "personal-unit-calendar"}
      data-node-count={nodeIds?.length ?? 0}
      data-node-ids={nodeIds?.join(",") ?? ""}
      data-soldier-id={soldierId ?? ""}
      data-highlight-soldier-id={highlightSoldierId ?? ""}
      data-scope={scope ?? ""}
    />
  ),
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: mockUser }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(mockUser, {
    id: "soldier-1",
    full_name: "חייל בדיקה",
    role: "soldier",
    hierarchy_node_id: null,
    is_commander: false,
    is_duty_manager: false,
  });
  vi.mocked(assignmentsApi.listEffectiveDuties).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.listLocations).mockResolvedValue([]);
  vi.mocked(swapsApi.listMySwaps).mockResolvedValue([]);
  vi.mocked(swapsApi.listPendingSwaps).mockResolvedValue([]);
  vi.mocked(enrollmentApi.listPendingEnrollments).mockResolvedValue([]);
  vi.mocked(systemSettingsApi.getSystemSettings).mockResolvedValue({});
  vi.mocked(scoringApi.getTransparency).mockResolvedValue({ rows: [], can_see_exemption_aggregates: false });
  vi.mocked(scoringApi.getBreakdown).mockResolvedValue({ per_type: [], adjustments: [] });
  vi.mocked(scoringApi.getBurdenShare).mockResolvedValue({
    has_group: false, burden_share: null, rank: null, group_size: null,
    duty_type_names: [], peer_scores: [], mean: null, stddev: null, cv: null, low_sample: false,
  });
  vi.mocked(scoringApi.getBurdenShareBreakdown).mockResolvedValue({ quarters: [], burden_share: "0", A_i: "0", W_i: "0" });
  vi.mocked(constraintsApi.getPendingCount).mockResolvedValue(0);
  vi.mocked(exemptionsApi.getPendingExemptionCount).mockResolvedValue(0);
  vi.mocked(soldiersApi.getPendingFieldUpdateCount).mockResolvedValue(0);
  vi.mocked(rangesApi.getRanges).mockResolvedValue([]);
  vi.mocked(hierarchyTransfersApi.listPendingTransferRequests).mockResolvedValue([]);
  vi.mocked(publicSettingsApi.getPublicSettings).mockResolvedValue({});
  vi.mocked(commandDashboardApi.getAlerts).mockResolvedValue([]);
  vi.mocked(commandDashboardApi.getPotential).mockResolvedValue([]);
  vi.mocked(commandDashboardApi.getUpcoming).mockResolvedValue([]);
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([
    {
      id: "node-1",
      level: "team",
      name: "צוות א",
      parent_id: null,
      commander_id: "soldier-1",
      commander_name: "חייל בדיקה",
      path_ids: ["node-1"],
      duty_managers: [],
      dm_manageable: true,
      can_edit: true,
    },
  ]);
  vi.mocked(potentialApi.getPotential).mockResolvedValue({
    node_id: "node-1",
    as_of: "2026-08-31",
    raw_eligible_count: 3,
    total_soldiers: 5,
    modifiers: [],
    final_potential: 3,
    soldiers: [],
    partial_exemption_count: 0,
  });
  vi.mocked(ineligibleSoldiersApi.getIneligibleSoldiers).mockResolvedValue({
    count: 0,
    nodes: [],
    soldiers: [],
  });
  vi.mocked(levelTypesApi.listLevelTypes).mockResolvedValue([]);
});

function renderHome() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SoldierModalProvider>
          <HomePage />
        </SoldierModalProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HomePage - required scoring data load errors", () => {
  it("shows a load error banner when the transparency response is malformed", async () => {
    vi.mocked(scoringApi.getTransparency).mockRejectedValue(new Error("Invalid transparency response"));
    renderHome();

    expect(await screen.findByText("home.score_load_error")).toHaveAttribute("role", "alert");
  });

  it("shows a load error banner when the score breakdown response is malformed", async () => {
    vi.mocked(scoringApi.getBreakdown).mockRejectedValue(new Error("Invalid score breakdown response"));
    renderHome();

    expect(await screen.findByText("home.score_load_error")).toHaveAttribute("role", "alert");
  });

  it("renders no scoring load-error banner when every scoring query succeeds", async () => {
    renderHome();

    await screen.findByText("home.welcome");
    expect(screen.queryByText("home.score_load_error")).not.toBeInTheDocument();
  });

  it("shows one highlighted command calendar with a visible scope label for management users", async () => {
    Object.assign(mockUser, {
      role: "commander",
      hierarchy_node_id: "node-1",
      is_commander: true,
    });

    renderHome();

    const commandSection = await screen.findByRole("region", { name: "ניהול היחידה" });
    expect(screen.getByText("היחידה / תת-העץ שבאחריותך")).toBeInTheDocument();

    const calendar = await screen.findByTestId("command-unit-calendar");
    expect(commandSection.compareDocumentPosition(calendar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(calendar).toHaveAttribute("data-scope", "command");
    expect(calendar).toHaveAttribute("data-highlight-soldier-id", "soldier-1");
    expect(screen.queryByTestId("personal-unit-calendar")).not.toBeInTheDocument();
  });

  it("keeps command queries and widgets off the regular soldier homepage while preserving personal widgets", async () => {
    renderHome();

    expect(await screen.findByTestId("personal-unit-calendar")).toHaveAttribute("data-soldier-id", "soldier-1");
    expect(screen.getByTestId("personal-unit-calendar")).toHaveAttribute("data-scope", "personal");
    expect(screen.queryByText("ניהול היחידה")).not.toBeInTheDocument();
    expect(screen.queryByTestId("command-unit-calendar")).not.toBeInTheDocument();

    await waitFor(() =>
      expect(assignmentsApi.listEffectiveDuties).toHaveBeenCalledWith(
        "soldier-1",
        expect.objectContaining({ include_drafts: true }),
      ),
    );
    expect(commandDashboardApi.getAlerts).not.toHaveBeenCalled();
    expect(commandDashboardApi.getPotential).not.toHaveBeenCalled();
    expect(commandDashboardApi.getUpcoming).not.toHaveBeenCalled();
    expect(hierarchyApi.fetchFullTree).not.toHaveBeenCalled();
    expect(potentialApi.getPotential).not.toHaveBeenCalled();
    expect(ineligibleSoldiersApi.getIneligibleSoldiers).not.toHaveBeenCalled();
    expect(enrollmentApi.listPendingEnrollments).not.toHaveBeenCalled();
    expect(swapsApi.listPendingSwaps).not.toHaveBeenCalled();
    expect(constraintsApi.getPendingCount).not.toHaveBeenCalled();
    expect(exemptionsApi.getPendingExemptionCount).not.toHaveBeenCalled();
    expect(soldiersApi.getPendingFieldUpdateCount).not.toHaveBeenCalled();
    expect(hierarchyTransfersApi.listPendingTransferRequests).not.toHaveBeenCalled();
  });

  it.each([
    { role: "commander" as const, flags: { is_commander: true, is_duty_manager: false } },
    { role: "duty_manager" as const, flags: { is_commander: false, is_duty_manager: true } },
    { role: "admin" as const, flags: { is_commander: false, is_duty_manager: false } },
  ])("renders the command composition and gates command queries on for $role users", async ({ role, flags }) => {
    vi.mocked(constraintsApi.getPendingCount).mockResolvedValue(1);
    Object.assign(mockUser, {
      role,
      hierarchy_node_id: "node-1",
      ...flags,
    });

    const { container } = renderHome();

    expect(await screen.findByText("ניהול היחידה")).toBeInTheDocument();
    expect(await screen.findByTestId("panel-ineligible-soldiers")).toBeInTheDocument();
    expect(screen.getByTestId("panel-alerts")).toBeInTheDocument();
    expect(screen.getByTestId("panel-approvals")).toBeInTheDocument();
    expect(screen.getByTestId("panel-upcoming")).toBeInTheDocument();
    expect(screen.getByTestId("panel-calendar")).toBeInTheDocument();
    expect(screen.getByTestId("panel-potential")).toBeInTheDocument();
    expect(screen.getByTestId("panel-own_potential")).toBeInTheDocument();
    expect(screen.getByTestId("command-unit-calendar")).toHaveAttribute("data-node-count", "1");
    expect(screen.queryByTestId("personal-unit-calendar")).not.toBeInTheDocument();
    expect(screen.getByTestId("command-unit-calendar")).toHaveAttribute("data-highlight-soldier-id", "soldier-1");
    expect(container.querySelectorAll('a[href="/approvals?tab=constraints"]')).toHaveLength(1);

    await waitFor(() => expect(commandDashboardApi.getAlerts).toHaveBeenCalledTimes(1));
    expect(commandDashboardApi.getPotential).toHaveBeenCalledTimes(1);
    expect(commandDashboardApi.getUpcoming).toHaveBeenCalledTimes(1);
    expect(hierarchyApi.fetchFullTree).toHaveBeenCalledTimes(1);
    expect(potentialApi.getPotential).toHaveBeenCalledWith("node-1");
    expect(ineligibleSoldiersApi.getIneligibleSoldiers).toHaveBeenCalledWith("commander");
    expect(enrollmentApi.listPendingEnrollments).toHaveBeenCalledTimes(1);
    expect(swapsApi.listPendingSwaps).toHaveBeenCalledTimes(1);
    expect(constraintsApi.getPendingCount).toHaveBeenCalledTimes(1);
    expect(exemptionsApi.getPendingExemptionCount).toHaveBeenCalledTimes(1);
    expect(soldiersApi.getPendingFieldUpdateCount).toHaveBeenCalledTimes(1);
    expect(hierarchyTransfersApi.listPendingTransferRequests).toHaveBeenCalledTimes(1);
  });

  it.each([
    { role: "duty_manager" as const, flags: { is_commander: false, is_duty_manager: true } },
    { role: "admin" as const, flags: { is_commander: false, is_duty_manager: false } },
  ])("uses the user's hierarchy node as the command calendar fallback for $role users", async ({ role, flags }) => {
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([
      {
        id: "other-node",
        level: "team",
        name: "צוות אחר",
        parent_id: null,
        commander_id: "someone-else",
        commander_name: "מפקד אחר",
        path_ids: ["other-node"],
        duty_managers: [],
        dm_manageable: true,
        can_edit: true,
      },
    ]);
    Object.assign(mockUser, {
      role,
      hierarchy_node_id: "authorized-node",
      ...flags,
    });

    renderHome();

    expect(await screen.findByTestId("command-unit-calendar")).toHaveAttribute("data-node-ids", "authorized-node");
  });
});
