import { render, screen } from "@testing-library/react";
import HierarchyTree from "./HierarchyTree";
import type { NodeDTO } from "../api/hierarchy";
import type { SoldierDTO } from "../api/soldiers";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../hooks/useLevelTypes", () => ({
  useLevelTypes: () => ({ levelTypes: [{ id: "lt1", key: "department", label: "מרכז", rank: 1 }] }),
}));

vi.mock("../api/dmScope", () => ({
  assignDmScope: vi.fn(),
  removeDmScope: vi.fn(),
  listDmScope: vi.fn().mockResolvedValue([]),
}));

function node(overrides: Partial<NodeDTO> = {}): NodeDTO {
  return {
    id: "node-1",
    level: "department",
    name: "מרכז א",
    parent_id: null,
    commander_id: null,
    commander_name: null,
    path_ids: ["node-1"],
    duty_managers: [],
    dm_manageable: false,
    ...overrides,
  };
}

const soldiers: SoldierDTO[] = [];

test("does not show the assign-duty-managers button when dm_manageable is false and viewer is not admin", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: false })]} soldiers={soldiers} isAdmin={false} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.queryByTestId("tree-dm-btn-node-1")).not.toBeInTheDocument();
});

test("shows the assign-duty-managers button when dm_manageable is true, even for a non-admin commander", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: true })]} soldiers={soldiers} isAdmin={false} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.getByTestId("tree-dm-btn-node-1")).toBeInTheDocument();
});

test("does not show admin-only buttons for a non-admin commander even when dm_manageable is true", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: true })]} soldiers={soldiers} isAdmin={false} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.queryByTestId("tree-commander-btn-node-1")).not.toBeInTheDocument();
  expect(screen.queryByTestId("tree-rename-node-1")).not.toBeInTheDocument();
});

test("renders duty manager names as clickable links", () => {
  render(
    <HierarchyTree
      nodes={[node({ duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }] })]}
      soldiers={soldiers}
      isAdmin={true}
      canManageLevelTypes={false}
      onChanged={vi.fn()}
    />
  );
  expect(screen.getByTestId("tree-dm-link-scope-1")).toHaveTextContent("דני כהן");
});
