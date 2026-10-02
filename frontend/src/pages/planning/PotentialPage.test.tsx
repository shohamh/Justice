import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { NodeDTO } from "../../api/hierarchy";
import type { PotentialResult, PotentialSummary } from "../../api/potential";
import { queryKeys } from "../../queryKeys";
import { WHOLE_ORG_ID } from "../../utils/wholeOrg";
import PotentialPage from "./PotentialPage";
import * as hierarchyApi from "../../api/hierarchy";
import * as potentialApi from "../../api/potential";

const auth = { ready: true, user: {
  id: "viewer-1", role: "admin" as const, scope_root_ids: ["root-a", "root-b"],
  active_deputy_grants: [], hierarchy_node_id: null, is_commander: false, is_duty_manager: false,
} };

function translate(key: string) { return key; }
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ user: auth.user, authScopeReady: auth.ready }) }));
vi.mock("../../components/Layout", () => ({ default: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../../components/SoldierLink", () => ({ default: ({ name }: { name: string }) => <span>{name}</span> }));
vi.mock("../../hooks/useLevelTypes", () => ({ useLevelTypes: () => ({ levelTypes: [] }) }));
vi.mock("../../api/hierarchy", () => ({ fetchFullTree: vi.fn() }));
vi.mock("../../api/potential", () => ({
  getPotential: vi.fn(), getPotentialSummary: vi.fn(), getBurdenShareGap: vi.fn(),
  listModifiers: vi.fn(), createModifier: vi.fn(), deleteModifier: vi.fn(),
}));
vi.mock("../../api/dutyConfig", () => ({ listDutyTypes: vi.fn().mockResolvedValue([]) }));

const rootA: NodeDTO = {
  id: "root-a", name: "Root A", level: "unit", parent_id: null, path_ids: ["root-a"],
  commander_id: null, commander_name: null, duty_managers: [], dm_manageable: false,
};
const childA: NodeDTO = {
  ...rootA, id: "child-a", name: "Child A", parent_id: "root-a", path_ids: ["root-a", "child-a"],
};
const rootB: NodeDTO = {
  ...rootA, id: "root-b", name: "Root B", path_ids: ["root-b"],
};

const summaries: Record<string, PotentialSummary> = {
  "root-a": { node_id: "root-a", as_of: "2026-10-02", raw_eligible_count: 2, total_soldiers: 3, partial_exemption_count: 1, modifier_total: 2, final_potential: 4 },
  "child-a": { node_id: "child-a", as_of: "2026-10-02", raw_eligible_count: 1, total_soldiers: 1, partial_exemption_count: 0, modifier_total: 0, final_potential: 1 },
  "root-b": { node_id: "root-b", as_of: "2026-10-02", raw_eligible_count: 1, total_soldiers: 2, partial_exemption_count: 0, modifier_total: -1, final_potential: 0 },
};

function detail(nodeId: string, soldierName: string): PotentialResult {
  const summary = summaries[nodeId];
  return {
    ...summary, modifiers: [],
    soldiers: [{ soldier_id: `${nodeId}-soldier`, full_name: soldierName, counted: true,
      reason: null, exemption_names: null, rank: null, partial_exemption_names: null,
      exemptions: null, eligible_duty_type_ids: [] }],
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  render(<QueryClientProvider client={client}><PotentialPage /></QueryClientProvider>);
  return client;
}

function expand(name: string) {
  const row = screen.getByRole("row", { name: new RegExp(name) });
  fireEvent.click(within(row).getByRole("button", { name: "הרחב" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  auth.ready = true;
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([rootA, childA, rootB]);
  vi.mocked(potentialApi.getPotentialSummary).mockImplementation(async (id) => summaries[id]);
  vi.mocked(potentialApi.getPotential).mockImplementation(async (id) => detail(id, `Soldier ${id}`));
  vi.mocked(potentialApi.getBurdenShareGap).mockResolvedValue([]);
  vi.mocked(potentialApi.listModifiers).mockResolvedValue([]);
});

describe("PotentialPage summary and detail loading", () => {
  it("shows aggregate and whole-org values using only compact summaries on first load", async () => {
    renderPage();
    const whole = await screen.findByRole("row", { name: /common.whole_org/ });
    await waitFor(() => expect(within(whole).getAllByRole("cell")[2]).toHaveTextContent("5"));
    expect(within(whole).getAllByRole("cell")[3]).toHaveTextContent("3");
    expect(within(whole).getAllByRole("cell")[4]).toHaveTextContent("1");
    expect(within(whole).getAllByRole("cell")[6]).toHaveTextContent("1");
    expect(within(whole).getAllByRole("cell")[7]).toHaveTextContent("4");
    expect(potentialApi.getPotentialSummary).toHaveBeenCalledTimes(3);
    expect(potentialApi.getPotential).not.toHaveBeenCalled();
  });

  it("loads soldier details for the expanded node alone", async () => {
    renderPage();
    await screen.findByRole("row", { name: /Root A/ });
    expand("Child A");
    expect(await screen.findByText("Soldier child-a")).toBeInTheDocument();
    expect(potentialApi.getPotential).toHaveBeenCalledTimes(1);
    expect(potentialApi.getPotential).toHaveBeenCalledWith("child-a", expect.any(String));
  });

  it("expands whole organization using real roots in root order only", async () => {
    renderPage();
    await screen.findByRole("row", { name: /common.whole_org/ });
    expand("common.whole_org");
    expect(await screen.findByText("Soldier root-a")).toBeInTheDocument();
    expect(await screen.findByText("Soldier root-b")).toBeInTheDocument();
    expect(potentialApi.getPotential).toHaveBeenCalledTimes(2);
    expect(vi.mocked(potentialApi.getPotential).mock.calls.map(([id]) => id).sort()).toEqual(["root-a", "root-b"]);
    const soldierRows = within(screen.getByTestId(`potential-soldiers-table-${WHOLE_ORG_ID}`)).getAllByRole("row");
    expect(soldierRows[1]).toHaveTextContent("Soldier root-a");
    expect(soldierRows[2]).toHaveTextContent("Soldier root-b");
  });

  it("shows a detail error and retries without replacing the summary", async () => {
    vi.mocked(potentialApi.getPotential).mockRejectedValueOnce(new Error("detail failed"));
    renderPage();
    await screen.findByRole("row", { name: /Root A/ });
    expand("Root A");
    expect(await screen.findByText("potential.details_load_error")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "potential.retry" }));
    expect(await screen.findByText("Soldier root-a")).toBeInTheDocument();
    expect(potentialApi.getPotential).toHaveBeenCalledTimes(2);
  });

  it("waits for the authorization scope before requesting summaries or details", async () => {
    auth.ready = false;
    const client = renderPage();
    await screen.findByTestId("potential-table");
    expect(hierarchyApi.fetchFullTree).not.toHaveBeenCalled();
    expect(potentialApi.getPotentialSummary).not.toHaveBeenCalled();
    expect(potentialApi.getPotential).not.toHaveBeenCalled();
    expect(client.getQueryData(queryKeys.potentialByNode("root-a", "2026-10-02"))).toBeUndefined();
  });
});
