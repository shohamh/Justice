import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AssignDutyManagersDialog from "./AssignDutyManagersDialog";
import type { NodeDTO } from "../api/hierarchy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockAssign = vi.fn();
const mockRemove = vi.fn();
vi.mock("../api/dmScope", () => ({
  assignDmScope: (...args: unknown[]) => mockAssign(...args),
  removeDmScope: (...args: unknown[]) => mockRemove(...args),
}));

const mockListSoldiers = vi.fn();
vi.mock("../api/soldiers", () => ({
  listSoldiers: () => mockListSoldiers(),
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
    dm_manageable: true,
    ...overrides,
  };
}

beforeEach(() => {
  mockAssign.mockReset();
  mockRemove.mockReset();
  mockListSoldiers.mockReset();
  mockListSoldiers.mockResolvedValue([
    { id: "s1", personal_number: "1001", full_name: "דני כהן" },
  ]);
  mockAssign.mockResolvedValue({ id: "scope-1", duty_manager_id: "s1", hierarchy_node_id: "node-1" });
  mockRemove.mockResolvedValue(undefined);
});

test("renders existing duty managers with a remove button each", () => {
  const n = node({
    duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }],
  });
  render(<AssignDutyManagersDialog node={n} onClose={vi.fn()} onChanged={vi.fn()} />);
  expect(screen.getByTestId("duty-managers-list")).toBeInTheDocument();
  expect(screen.getByText("דני כהן")).toBeInTheDocument();
  expect(screen.getByTestId("remove-dm-scope-1")).toBeInTheDocument();
});

test("shows empty state when node has no duty managers", () => {
  render(<AssignDutyManagersDialog node={node()} onClose={vi.fn()} onChanged={vi.fn()} />);
  expect(screen.queryByTestId("duty-managers-list")).not.toBeInTheDocument();
});

test("clicking remove calls removeDmScope and onChanged", async () => {
  const onChanged = vi.fn();
  const n = node({
    duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }],
  });
  render(<AssignDutyManagersDialog node={n} onClose={vi.fn()} onChanged={onChanged} />);
  fireEvent.click(screen.getByTestId("remove-dm-scope-1"));
  await waitFor(() => expect(mockRemove).toHaveBeenCalledWith("scope-1"));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
});

test("typing and selecting a soldier calls assignDmScope and onChanged", async () => {
  const onChanged = vi.fn();
  render(<AssignDutyManagersDialog node={node()} onClose={vi.fn()} onChanged={onChanged} />);
  await waitFor(() => expect(mockListSoldiers).toHaveBeenCalled());
  const input = screen.getByTestId("duty-manager-search");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "דני" } });
  await waitFor(() => expect(screen.getByTestId("duty-manager-option-s1")).toBeInTheDocument());
  fireEvent.mouseDown(screen.getByTestId("duty-manager-option-s1"));
  await waitFor(() => expect(mockAssign).toHaveBeenCalledWith("s1", "node-1"));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
});

test("does not offer an already-assigned soldier in the search dropdown", async () => {
  mockListSoldiers.mockResolvedValue([
    { id: "s1", personal_number: "1001", full_name: "דני כהן" },
    { id: "s2", personal_number: "1002", full_name: "יוסי לוי" },
  ]);
  const n = node({
    duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }],
  });
  render(<AssignDutyManagersDialog node={n} onClose={vi.fn()} onChanged={vi.fn()} />);
  await waitFor(() => expect(mockListSoldiers).toHaveBeenCalled());
  const input = screen.getByTestId("duty-manager-search");
  fireEvent.focus(input);
  await waitFor(() => expect(screen.getByTestId("duty-manager-option-s2")).toBeInTheDocument());
  expect(screen.queryByTestId("duty-manager-option-s1")).not.toBeInTheDocument();
});
