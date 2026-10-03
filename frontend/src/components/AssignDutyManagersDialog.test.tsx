import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AssignDutyManagersDialog from "./AssignDutyManagersDialog";
import type { NodeDTO } from "../api/hierarchy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => ({
      "errors.forbidden": "אין הרשאה לבצע פעולה זו",
      "errors.generic": "שגיאה",
    }[key] ?? key),
  }),
}));

const mockAssign = vi.fn();
const mockRemove = vi.fn();
vi.mock("../api/dmScope", () => ({
  assignDmScope: (...args: unknown[]) => mockAssign(...args),
  removeDmScope: (...args: unknown[]) => mockRemove(...args),
}));

const mockListSoldierRosterPage = vi.fn();
vi.mock("../api/soldiers", () => ({
  listSoldierRosterPage: (...args: unknown[]) => mockListSoldierRosterPage(...args),
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "admin-1",
      role: "admin",
      hierarchy_node_id: null,
      scope_root_ids: [],
      active_deputy_grants: [],
      is_commander: false,
      is_duty_manager: false,
    },
    authScopeReady: true,
  }),
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
  mockListSoldierRosterPage.mockReset().mockResolvedValue({
    items: [{
      id: "s1", personal_number: "1001", full_name: "דני כהן", role: "soldier",
      hierarchy_node_id: null, left_at: null, telegram_linked: false, is_commander: false,
      commander_node_name: null, hierarchy_path: [],
    }],
    next_cursor: null,
    has_more: false,
  });
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
  const input = screen.getByTestId("duty-manager-search");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "דני" } });
  await waitFor(() => expect(mockListSoldierRosterPage).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByTestId("duty-manager-option-s1")).toBeInTheDocument());
  fireEvent.mouseDown(screen.getByTestId("duty-manager-option-s1"));
  await waitFor(() => expect(mockAssign).toHaveBeenCalledWith("s1", "node-1"));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
});

test("does not offer an already-assigned soldier in the search dropdown", async () => {
  mockListSoldierRosterPage.mockResolvedValue({
    items: [
      { id: "s1", personal_number: "1001", full_name: "דני כהן", role: "soldier", hierarchy_node_id: null, left_at: null, telegram_linked: false, is_commander: false, commander_node_name: null, hierarchy_path: [] },
      { id: "s2", personal_number: "1002", full_name: "יוסי לוי", role: "soldier", hierarchy_node_id: null, left_at: null, telegram_linked: false, is_commander: false, commander_node_name: null, hierarchy_path: [] },
    ],
    next_cursor: null,
    has_more: false,
  });
  const n = node({
    duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }],
  });
  render(<AssignDutyManagersDialog node={n} onClose={vi.fn()} onChanged={vi.fn()} />);
  const input = screen.getByTestId("duty-manager-search");
  fireEvent.focus(input);
  await waitFor(() => expect(mockListSoldierRosterPage).toHaveBeenCalled());
  await waitFor(() => expect(screen.getByTestId("duty-manager-option-s2")).toBeInTheDocument());
  expect(screen.queryByTestId("duty-manager-option-s1")).not.toBeInTheDocument();
});

test("shows the translated backend detail when assigning fails", async () => {
  mockAssign.mockRejectedValue({ response: { status: 403, data: { detail: "forbidden" } } });
  render(<AssignDutyManagersDialog node={node()} onClose={vi.fn()} onChanged={vi.fn()} />);
  fireEvent.focus(screen.getByTestId("duty-manager-search"));
  await waitFor(() => expect(mockListSoldierRosterPage).toHaveBeenCalled());
  fireEvent.mouseDown(await screen.findByTestId("duty-manager-option-s1"));

  expect(await screen.findByText("אין הרשאה לבצע פעולה זו")).toBeInTheDocument();
});

test("shows the translated backend detail when removing fails", async () => {
  mockRemove.mockRejectedValue({ response: { status: 403, data: { detail: "forbidden" } } });
  const n = node({
    duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }],
  });
  render(<AssignDutyManagersDialog node={n} onClose={vi.fn()} onChanged={vi.fn()} />);

  fireEvent.click(screen.getByTestId("remove-dm-scope-1"));

  expect(await screen.findByText("אין הרשאה לבצע פעולה זו")).toBeInTheDocument();
});
