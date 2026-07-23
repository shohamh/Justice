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
    can_edit: false,
    ...overrides,
  };
}

const soldiers: SoldierDTO[] = [];

test("does not show the assign-duty-managers button when dm_manageable is false and viewer cannot edit the node", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: false, can_edit: false })]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.queryByTestId("tree-dm-btn-node-1")).not.toBeInTheDocument();
});

test("shows the assign-duty-managers button when dm_manageable is true, even for a non-admin commander", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: true, can_edit: false })]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.getByTestId("tree-dm-btn-node-1")).toBeInTheDocument();
});

test("does not show can_edit-gated buttons for a non-admin commander even when dm_manageable is true", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: true, can_edit: false })]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.queryByTestId("tree-commander-btn-node-1")).not.toBeInTheDocument();
  expect(screen.queryByTestId("tree-rename-node-1")).not.toBeInTheDocument();
});

test("shows can_edit-gated buttons when the node's can_edit flag is true", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: false, can_edit: true })]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.getByTestId("tree-commander-btn-node-1")).toBeInTheDocument();
  expect(screen.getByTestId("tree-rename-node-1")).toBeInTheDocument();
});

test("renders duty manager names as clickable links", () => {
  render(
    <HierarchyTree
      nodes={[node({ duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }], can_edit: true })]}
      soldiers={soldiers}
      canManageLevelTypes={false}
      onChanged={vi.fn()}
    />
  );
  expect(screen.getByTestId("tree-dm-link-scope-1")).toHaveTextContent("דני כהן");
});

test("auto-expands down to and highlights the viewer's own commanded node, beyond the default two levels", () => {
  render(
    <HierarchyTree
      nodes={[
        node({ id: "root", name: "שורש", parent_id: null, path_ids: ["root"], can_edit: false }),
        node({ id: "a", name: "רמה א", parent_id: "root", path_ids: ["root", "a"], can_edit: false }),
        node({ id: "b", name: "רמה ב", parent_id: "a", path_ids: ["root", "a", "b"], can_edit: false }),
        node({ id: "child", name: "יחידה שלי", parent_id: "b", path_ids: ["root", "a", "b", "child"], can_edit: true }),
      ]}
      soldiers={soldiers}
      canManageLevelTypes={false}
      onChanged={vi.fn()}
    />
  );
  // "b" is at depth 3, past the default two-level auto-expand, so its child ("child")
  // only renders if the tree specifically auto-expanded down to the viewer's own node.
  expect(screen.getByTestId("tree-rename-child")).toBeInTheDocument();
  expect(screen.getByTestId("tree-name-child").closest("li")).toHaveClass("bg-indigo-50");
});
