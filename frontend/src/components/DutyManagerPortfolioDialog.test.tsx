import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import DutyManagerPortfolioDialog from "./DutyManagerPortfolioDialog";
import type { NodeDTO } from "../api/hierarchy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockList = vi.fn();
const mockAssign = vi.fn();
const mockRemove = vi.fn();
vi.mock("../api/dmScope", () => ({
  listDmScope: (...args: unknown[]) => mockList(...args),
  assignDmScope: (...args: unknown[]) => mockAssign(...args),
  removeDmScope: (...args: unknown[]) => mockRemove(...args),
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

const nodes: NodeDTO[] = [
  node({ id: "node-1", name: "מרכז א", dm_manageable: true }),
  node({ id: "node-2", name: "מרכז ב", parent_id: null, dm_manageable: false }),
];

beforeEach(() => {
  mockList.mockReset();
  mockAssign.mockReset();
  mockRemove.mockReset();
  mockList.mockResolvedValue([{ id: "scope-1", duty_manager_id: "s1", hierarchy_node_id: "node-1" }]);
  mockAssign.mockResolvedValue({ id: "scope-2", duty_manager_id: "s1", hierarchy_node_id: "node-2" });
  mockRemove.mockResolvedValue(undefined);
});

test("loads and renders the soldier's current portfolio", async () => {
  render(
    <DutyManagerPortfolioDialog soldierId="s1" soldierName="דני כהן" nodes={nodes} onClose={vi.fn()} onChanged={vi.fn()} />
  );
  await waitFor(() => expect(mockList).toHaveBeenCalledWith("s1"));
  await waitFor(() => expect(screen.getByText("מרכז א")).toBeInTheDocument());
});

test("only offers dm_manageable nodes in the add combobox", async () => {
  render(
    <DutyManagerPortfolioDialog soldierId="s1" soldierName="דני כהן" nodes={nodes} onClose={vi.fn()} onChanged={vi.fn()} />
  );
  await waitFor(() => expect(mockList).toHaveBeenCalled());
  const combo = screen.getByTestId("portfolio-add-node");
  fireEvent.focus(combo);
  expect(screen.queryByText("מרכז ב")).not.toBeInTheDocument();
});

test("removing an entry calls removeDmScope, refetches, and calls onChanged", async () => {
  const onChanged = vi.fn();
  render(
    <DutyManagerPortfolioDialog soldierId="s1" soldierName="דני כהן" nodes={nodes} onClose={vi.fn()} onChanged={onChanged} />
  );
  await waitFor(() => expect(screen.getByTestId("remove-portfolio-scope-1")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("remove-portfolio-scope-1"));
  await waitFor(() => expect(mockRemove).toHaveBeenCalledWith("scope-1"));
  await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
});

test("does not offer a node already in the soldier's portfolio in the add combobox", async () => {
  render(
    <DutyManagerPortfolioDialog soldierId="s1" soldierName="דני כהן" nodes={nodes} onClose={vi.fn()} onChanged={vi.fn()} />
  );
  await waitFor(() => expect(screen.getByText("מרכז א")).toBeInTheDocument());
  const combo = screen.getByTestId("portfolio-add-node");
  fireEvent.focus(combo);
  // "מרכז א" (node-1) is already in the portfolio (mockList resolves it) — it
  // appears once in the rendered portfolio list, but must NOT also appear as a
  // selectable option in the combobox dropdown.
  const options = screen.getAllByText("מרכז א");
  expect(options.length).toBe(1);
});
