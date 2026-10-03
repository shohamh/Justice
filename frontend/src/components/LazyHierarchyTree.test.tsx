import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as hierarchyApi from "../api/hierarchy";
import LazyHierarchyTree from "./LazyHierarchyTree";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../api/hierarchy");
vi.mock("../api/soldiers");
vi.mock("../contexts/SoldierModalContext", () => ({ useSoldierModal: () => ({ openSoldierModal: vi.fn() }) }));
vi.mock("../hooks/useLevelTypes", () => ({ useLevelTypes: () => ({ levelTypes: [], loading: false, refresh: vi.fn() }) }));
vi.mock("./CursorPagedTable", () => ({
  default: ({ tableLabel }: { tableLabel: string }) => <div data-testid="roster-table">{tableLabel}</div>,
}));
vi.mock("./PopoverDropdown", () => ({ default: () => null }));

const leaf = {
  id: "leaf-1",
  name: "Soldier Leaf",
  level: "team" as const,
  parent_id: null,
  commander_id: null,
  commander_name: null,
  path_ids: ["leaf-1"],
  duty_managers: [],
  dm_manageable: false,
  can_edit: false,
  has_children: false,
  has_soldiers: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(hierarchyApi.fetchHierarchyBranchPage).mockResolvedValue({
    items: [leaf],
    next_cursor: null,
    has_more: false,
  });
});

describe("LazyHierarchyTree", () => {
  it("does not offer expansion for a soldier-containing leaf and still opens its roster", async () => {
    const onSelectedNodeChange = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <LazyHierarchyTree
          scopeKey="viewer-scope"
          roleOrder={[]}
          canManageLevelTypes={false}
          onChanged={vi.fn()}
          onSelectedNodeChange={onSelectedNodeChange}
          onOpenPortfolio={vi.fn()}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Soldier Leaf")).toBeInTheDocument();
    expect(screen.queryByTestId("tree-toggle-leaf-1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("tree-name-leaf-1"));

    expect(onSelectedNodeChange).toHaveBeenCalledWith(leaf);
    expect(await screen.findByTestId("selected-node-roster")).toBeInTheDocument();
    expect(screen.getByTestId("roster-table")).toHaveTextContent("team.soldiers_in_node");
  });
});
