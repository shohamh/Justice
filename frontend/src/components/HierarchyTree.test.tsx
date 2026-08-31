import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import HierarchyTree from "./HierarchyTree";
import type { NodeDTO } from "../api/hierarchy";
import type { SoldierDTO } from "../api/soldiers";
import { deleteNode } from "../api/hierarchy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const LOADED_LEVEL_TYPES = { levelTypes: [{ id: "lt1", key: "department", label: "מרכז", rank: 1 }], loading: false };
const mockUseLevelTypes = vi.fn(() => LOADED_LEVEL_TYPES);
vi.mock("../hooks/useLevelTypes", () => ({
  useLevelTypes: () => mockUseLevelTypes(),
}));

vi.mock("../api/hierarchy", () => ({
  deleteNode: vi.fn(),
  moveNode: vi.fn(),
}));

afterEach(() => {
  mockUseLevelTypes.mockReturnValue(LOADED_LEVEL_TYPES);
});

vi.mock("../api/dmScope", () => ({
  assignDmScope: vi.fn(),
  removeDmScope: vi.fn(),
  listDmScope: vi.fn().mockResolvedValue([]),
}));

vi.mock("./SoldierLink", () => ({
  default: ({ id, name, className }: { id: string; name: string; className?: string }) => <button className={className} data-testid={`soldier-link-${id}`}>{name}</button>,
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

const editableSoldier = {
  id: "soldier-1",
  personal_number: "1234567",
  full_name: "×—×™×™×œ ×‘×“×™×§×”",
  hierarchy_node_id: "node-1",
  telegram_linked: false,
} as SoldierDTO;

test("shows the translated level badge once level types have loaded", () => {
  render(
    <HierarchyTree nodes={[node()]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.getByText("מרכז")).toBeInTheDocument();
});

test("hides the level badge (never shows the raw level key) while level types are still loading", () => {
  mockUseLevelTypes.mockReturnValue({ levelTypes: [], loading: true });
  render(
    <HierarchyTree nodes={[node()]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.queryByText("department")).not.toBeInTheDocument();
  expect(screen.queryByText("מרכז")).not.toBeInTheDocument();
});

test("does not show hierarchy action buttons when viewer cannot edit the node", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: false, can_edit: false })]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.queryByTestId("tree-add-soldier-node-1")).not.toBeInTheDocument();
  expect(screen.queryByTestId("tree-commander-btn-node-1")).not.toBeInTheDocument();
});

test("shows the duty-manager action when dm_manageable is true, even for a non-admin commander", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: true, can_edit: false })]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.getByTestId("tree-dm-btn-node-1")).toBeInTheDocument();
});

test("does not show can_edit-gated actions for a non-admin commander even when dm_manageable is true", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: true, can_edit: false })]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.queryByTestId("tree-commander-btn-node-1")).not.toBeInTheDocument();
  expect(screen.queryByTestId("tree-edit-name-node-1")).not.toBeInTheDocument();
});

test("shows can_edit-gated actions when the node's can_edit flag is true", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: false, can_edit: true })]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.getByTestId("tree-commander-btn-node-1")).toBeInTheDocument();
  expect(screen.getByTestId("tree-edit-name-node-1")).toBeInTheDocument();
  expect(screen.getByTestId("tree-delete-node-1")).toHaveAttribute("title", "duty_config.delete");
  expect(screen.getByTestId("tree-commander-btn-node-1")).toHaveClass("h-7");
  expect(screen.getByTestId("tree-delete-node-1")).toHaveClass("h-7");
  expect(screen.getByTestId("tree-commander-unassigned-node-1")).toHaveTextContent("לא מוגדר");
  expect(screen.getByTestId("tree-commander-unassigned-node-1")).toHaveClass("text-red-600");
});

test("keeps the trash action visible but disabled when the hierarchy contains soldiers", () => {
  render(
    <HierarchyTree
      nodes={[node({ can_edit: true })]}
      soldiers={[editableSoldier]}
      canManageLevelTypes={false}
      onChanged={vi.fn()}
    />
  );

  expect(screen.getByTestId("tree-delete-node-1")).toBeDisabled();
  expect(screen.getByTestId("tree-delete-node-1")).toHaveAttribute("title", "לא ניתן למחוק היררכיה שיש בה חיילים או תתי היררכיות");
});

test("only deletes a hierarchy node after confirming in the application dialog", async () => {
  const onChanged = vi.fn();
  vi.mocked(deleteNode).mockResolvedValueOnce();
  const nativeConfirm = vi.spyOn(window, "confirm");

  render(
    <HierarchyTree nodes={[node({ can_edit: true })]} soldiers={soldiers} canManageLevelTypes={false} onChanged={onChanged} />
  );

  fireEvent.click(screen.getByTestId("tree-delete-node-1"));
  expect(nativeConfirm).not.toHaveBeenCalled();
  expect(deleteNode).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));

  await waitFor(() => expect(deleteNode).toHaveBeenCalledWith("node-1"));
  expect(onChanged).toHaveBeenCalledTimes(1);
  nativeConfirm.mockRestore();
});

test("renders the compact actions menu for small viewports", () => {
  render(
    <HierarchyTree nodes={[node({ can_edit: true })]} soldiers={soldiers} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.getByTestId("tree-actions-menu-node-1")).toBeInTheDocument();
});

test("renders duty manager names as clickable links outside the actions menu", () => {
  render(
    <HierarchyTree
      nodes={[node({ duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }], can_edit: true })]}
      soldiers={soldiers}
      canManageLevelTypes={false}
      onChanged={vi.fn()}
    />
  );
  expect(screen.getByTestId("tree-dm-name-scope-1")).toHaveTextContent("דני כהן");
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
  expect(screen.getByTestId("tree-name-child")).toBeInTheDocument();
  expect(screen.getByTestId("tree-name-child").closest("li")).toHaveClass("bg-indigo-50");
});

test("renders the soldier edit action as a pencil icon with an accessible label", () => {
  render(
    <HierarchyTree
      nodes={[node({ can_edit: true })]}
      soldiers={[editableSoldier]}
      canManageLevelTypes={false}
      onChanged={vi.fn()}
    />
  );

  const editButton = screen.getByTestId("edit-soldier-1234567");
  expect(editButton).toHaveTextContent("✏️");
  expect(editButton).toHaveAttribute("aria-label", "team.edit");
  expect(editButton).toHaveAttribute("title", "team.edit");
  expect(screen.queryByText("(1234567)")).not.toBeInTheDocument();
});

test("links the commander and exposes inline pencil actions for editable hierarchy details", () => {
  const commander = { ...editableSoldier, id: "commander-1", full_name: "מפקד" };

  render(
    <HierarchyTree
      nodes={[node({
        can_edit: true,
        dm_manageable: true,
        commander_id: commander.id,
        commander_name: commander.full_name,
        duty_managers: [{ scope_id: "scope-1", soldier_id: "dm-1", name: "אחראי" }],
      })]}
      soldiers={[commander]}
      canManageLevelTypes={false}
      onChanged={vi.fn()}
    />
  );

  expect(screen.getAllByTestId("soldier-link-commander-1")).toHaveLength(2);
  expect(screen.getByTestId("tree-edit-name-node-1")).toHaveAttribute("aria-label", "team.edit");
  expect(screen.getByTestId("tree-commander-btn-node-1")).toHaveAttribute("aria-label", "team.assign_commander");
  expect(screen.getByTestId("tree-dm-btn-node-1")).toHaveAttribute("aria-label", "team.assign_duty_managers");
});

test("uses compact action icons with tooltips and places assigned names beneath them", () => {
  const commander = { ...editableSoldier, id: "commander-1", full_name: "מפקד" };
  mockUseLevelTypes.mockReturnValue({
    levelTypes: [
      { id: "lt1", key: "department", label: "מרכז", rank: 1 },
      { id: "lt2", key: "team", label: "צוות", rank: 2 },
    ],
    loading: false,
  });

  render(
    <HierarchyTree
      nodes={[node({
        can_edit: true,
        dm_manageable: true,
        commander_id: commander.id,
        commander_name: commander.full_name,
        duty_managers: [{ scope_id: "scope-1", soldier_id: "dm-1", name: "אחראי" }],
      })]}
      soldiers={[commander]}
      canManageLevelTypes={false}
      onChanged={vi.fn()}
    />
  );

  expect(screen.getByTestId("tree-add-child-node-1")).toHaveAttribute("title", "team.add_node");
  expect(screen.getByTestId("tree-add-soldier-node-1")).toHaveAttribute("title", "team.add_soldier");
  expect(screen.getByTestId("tree-commander-btn-node-1")).toHaveAttribute("title", "team.assign_commander");
  expect(screen.getByTestId("tree-dm-btn-node-1")).toHaveAttribute("title", "team.assign_duty_managers");
  expect(screen.getByTestId("tree-commander-name-node-1")).toHaveTextContent("מפקד");
  expect(screen.getByTestId("tree-dm-name-scope-1")).toHaveTextContent("אחראי");
  expect(screen.getByTestId("tree-edit-name-node-1")).toHaveClass("border");
  expect(screen.getByTestId("tree-add-child-node-1")).toHaveClass("border");
  expect(screen.getByTestId("tree-add-child-node-1")).toHaveClass("h-7");
  expect(screen.getByTestId("tree-add-soldier-node-1")).toHaveClass("h-7");
  expect(screen.getByTestId("tree-commander-btn-node-1")).toHaveClass("h-7");
  expect(screen.getByTestId("tree-dm-btn-node-1")).toHaveClass("h-7");
  expect(screen.getByTestId("tree-commander-name-node-1")).toHaveClass("whitespace-normal");
  expect(screen.getByTestId("tree-dm-names-node-1")).toHaveClass("whitespace-normal");
  expect(screen.getByTestId("tree-commander-name-node-1")).toHaveClass("w-12", "line-clamp-2");
  expect(screen.getByTestId("tree-dm-names-node-1")).toHaveClass("w-12", "line-clamp-2");
  expect(screen.getByTestId("tree-commander-name-node-1")).toHaveClass("break-words");
  expect(screen.getByTestId("tree-dm-names-node-1")).toHaveClass("break-words");
  expect(within(screen.getByTestId("tree-commander-name-node-1")).getByTestId("soldier-link-commander-1")).toHaveClass("block", "w-full", "text-center");
  expect(screen.getByTestId("tree-dm-name-scope-1")).toHaveClass("block", "w-full", "text-center");
  expect(screen.getByTestId("tree-action-group-node-1")).toHaveClass("grid-cols-5", "sm:grid");
  expect(screen.getByTestId("tree-commander-name-node-1")).toHaveClass("leading-3");
  expect(screen.getByTestId("tree-dm-names-node-1")).toHaveClass("leading-3");
});
