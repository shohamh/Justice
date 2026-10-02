import { beforeEach, describe, test, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as XLSX from "xlsx";
import "../../i18n";
import { dfsOrder } from "./ExportPage";
import ExportPage from "./ExportPage";
import type { NodeDTO } from "../../api/hierarchy";
import * as hierarchyApi from "../../api/hierarchy";
import * as scoringApi from "../../api/scoring";
import type { TransparencyRow } from "../../api/scoring";

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function mockNode(id: string, name: string, parent_id: string | null): NodeDTO {
  return {
    id,
    name,
    parent_id,
    level: "unit",
    commander_id: null,
    commander_name: null,
    path_ids: [],
    duty_managers: [],
    dm_manageable: true,
  };
}

test("dfsOrder groups children under their parent, not globally alphabetically", () => {
  // Root B comes before Root A alphabetically as siblings, but each root's
  // own children must stay nested under it, not interleaved globally.
  const nodes = [
    mockNode("root-a", "Alpha HQ", null),
    mockNode("root-b", "Bravo HQ", null),
    mockNode("a-child-2", "Zulu Squad", "root-a"),
    mockNode("a-child-1", "Echo Squad", "root-a"),
    mockNode("b-child-1", "Delta Squad", "root-b"),
  ];
  const order = dfsOrder(nodes);
  expect(order).toEqual(["root-a", "a-child-1", "a-child-2", "root-b", "b-child-1"]);
  // If the old buggy implementation were still in place, this would instead
  // produce a flat alphabetical-by-name order across ALL nodes regardless of
  // parent, e.g. interleaving "b-child-1" (Delta) between root-a's children.
});

vi.mock("../../api/scoring", () => ({ getTransparency: vi.fn().mockResolvedValue({ rows: [] }) }));
vi.mock("../../api/hierarchy", () => ({ fetchFullTree: vi.fn().mockResolvedValue([]) }));
vi.mock("../../api/client", () => ({ getAccessToken: vi.fn().mockReturnValue("test-token") }));
vi.mock("xlsx", async () => {
  const actual = await vi.importActual<typeof import("xlsx")>("xlsx");
  return { ...actual, writeFile: vi.fn() };
});
vi.mock("../../auth/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "viewer-1",
      role: "admin",
      scope_root_ids: [],
      active_deputy_grants: [],
      hierarchy_node_id: null,
      is_commander: false,
      is_duty_manager: false,
    },
    authScopeReady: true,
  }),
}));
vi.mock("../../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

global.fetch = vi.fn().mockResolvedValue({
  ok: true,
  arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
});

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function checkboxAt(index: number): HTMLInputElement {
  return screen.getAllByRole("checkbox")[index] as HTMLInputElement;
}

function transparencyRow(
  soldierId: string,
  fullName: string,
  nodeId: string | null,
  nodeName: string | null,
  overrides: Partial<TransparencyRow> = {},
): TransparencyRow {
  return {
    soldier_id: soldierId,
    full_name: fullName,
    node_id: nodeId,
    node_name: nodeName,
    enrolled_at: "2026-01-01",
    active_days: 10,
    shift_count: 2,
    rank: null,
    is_officer: false,
    service_type: null,
    cumulative_score: "10",
    score_per_day: "1.5",
    normalised_score: "2",
    is_globally_exempted: false,
    burden_share: 1,
    c_over_d: 1,
    burden_share_offset_raw: 0,
    exemptions_display: "",
    exemptions_visible: false,
    exemptions: [],
    has_global_exemption: null,
    has_partial_exemption: null,
    has_temporary_exemption: null,
    ...overrides,
  };
}

describe("ExportPage", () => {
  it("renders one checkbox per exportable data type and a single export button", async () => {
    renderWithProviders(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    expect(screen.getByLabelText(/בחר הכל/)).toBeInTheDocument();
    expect(screen.getByLabelText(/שקיפות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/תתי-יחידות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/סוגי תורנות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/מיקומי תורנות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/היררכיה/)).toBeInTheDocument();
    expect(screen.getByLabelText(/פטורים/)).toBeInTheDocument();
    expect(screen.getByLabelText(/הגדרות מערכת/)).toBeInTheDocument();
    expect(screen.getByLabelText(/דוחות תקלות/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^חיילים$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^משמרות$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^שיבוצים$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/תבניות תורנות/)).toBeInTheDocument();
  });

  it("selects and deselects every checkbox via the select-all control", async () => {
    renderWithProviders(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    const selectAll = screen.getByLabelText(/בחר הכל/) as HTMLInputElement;
    const transparency = screen.getByLabelText(/שקיפות/) as HTMLInputElement;
    const soldiers = screen.getByLabelText(/^חיילים$/) as HTMLInputElement;

    fireEvent.click(selectAll);
    expect(transparency.checked).toBe(true);
    expect(soldiers.checked).toBe(true);
    expect(selectAll.checked).toBe(true);

    fireEvent.click(selectAll);
    expect(transparency.checked).toBe(false);
    expect(soldiers.checked).toBe(false);
    expect(selectAll.checked).toBe(false);
  });

  it("calls /config/export with only the checked config sheets when export is clicked", async () => {
    renderWithProviders(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    fireEvent.click(screen.getByLabelText(/סוגי תורנות/));
    fireEvent.click(screen.getByText("ייצוא"));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/config/export?sheets=duty_types"),
        expect.anything(),
      );
    });
  });

  it("calls /import/export with only the checked data sheets when export is clicked", async () => {
    const importWb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(importWb, XLSX.utils.aoa_to_sheet([["personal_number"], ["123"]]), "soldiers");
    const importBuf = XLSX.write(importWb, { type: "array", bookType: "xlsx" });

    const fetchMock = vi.fn().mockResolvedValue({
      arrayBuffer: () => Promise.resolve(importBuf),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(<ExportPage />);
    fireEvent.click(await screen.findByLabelText(/^חיילים$/));
    fireEvent.click(screen.getByText("ייצוא"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/import/export?sheets=soldiers",
        expect.objectContaining({ headers: expect.any(Object) }),
      );
    });
  });

  it("renders checkboxes for the new range sheets", async () => {
    renderWithProviders(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    expect(screen.getByLabelText(/מיקומי מטווח/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^מטווחים$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/שיבוצי מטווח/)).toBeInTheDocument();
  });

  it("calls /config/export with range_locations when checked", async () => {
    renderWithProviders(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    fireEvent.click(screen.getByLabelText(/מיקומי מטווח/));
    fireEvent.click(screen.getByText("ייצוא"));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/config/export?sheets=range_locations"),
        expect.anything(),
      );
    });
  });

  it("calls /import/export with range_events and range_assignments when checked", async () => {
    const importWb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(importWb, XLSX.utils.aoa_to_sheet([["hierarchy_node_name"], ["מדור א"]]), "range_events");
    const importBuf = XLSX.write(importWb, { type: "array", bookType: "xlsx" });
    const fetchMock = vi.fn().mockResolvedValue({ arrayBuffer: () => Promise.resolve(importBuf) });
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(<ExportPage />);
    fireEvent.click(await screen.findByLabelText(/^מטווחים$/));
    fireEvent.click(await screen.findByLabelText(/שיבוצי מטווח/));
    fireEvent.click(screen.getByText("ייצוא"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/import/export?sheets=range_events,range_assignments",
        expect.objectContaining({ headers: expect.any(Object) }),
      );
    });
  });

  it("does not fetch transparency rows or the tree for a configuration-only export", async () => {
    const configWb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(configWb, XLSX.utils.aoa_to_sheet([["setting"]]), "duty_types");
    const configBuffer = XLSX.write(configWb, { type: "array", bookType: "xlsx" });
    const fetchMock = vi.fn().mockResolvedValue({
      arrayBuffer: () => Promise.resolve(configBuffer),
    });
    vi.stubGlobal("fetch", fetchMock);
    const writeFile = vi.mocked(XLSX.writeFile);

    renderWithProviders(<ExportPage />);
    fireEvent.click(checkboxAt(3));
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/config/export?sheets=duty_types"),
      expect.anything(),
    ));
    expect(scoringApi.getTransparency).not.toHaveBeenCalled();
    expect(hierarchyApi.fetchFullTree).not.toHaveBeenCalled();
    expect(writeFile).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["transparency", 1],
    ["sub-units", 2],
  ] as const)("loads both required payloads when %s is selected", async (_sheet, checkboxIndex) => {
    vi.mocked(scoringApi.getTransparency).mockResolvedValue({ rows: [], can_see_exemption_aggregates: false });
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
    renderWithProviders(<ExportPage />);
    fireEvent.click(checkboxAt(checkboxIndex));

    await waitFor(() => {
      expect(scoringApi.getTransparency).toHaveBeenCalledTimes(1);
      expect(hierarchyApi.fetchFullTree).toHaveBeenCalledTimes(1);
    });
  });

  it("disables export until the selected transparency rows and hierarchy finish loading", async () => {
    let resolveRows!: (value: { rows: TransparencyRow[]; can_see_exemption_aggregates: boolean }) => void;
    vi.mocked(scoringApi.getTransparency).mockReturnValue(new Promise((resolve) => { resolveRows = resolve; }));
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
    const writeFile = vi.mocked(XLSX.writeFile);
    renderWithProviders(<ExportPage />);
    fireEvent.click(checkboxAt(1));

    await waitFor(() => expect(scoringApi.getTransparency).toHaveBeenCalledTimes(1));
    const exportButton = screen.getByRole("button");
    expect(exportButton).toBeDisabled();
    fireEvent.click(exportButton);
    expect(writeFile).not.toHaveBeenCalled();

    resolveRows({ rows: [], can_see_exemption_aggregates: false });
    await waitFor(() => expect(exportButton).toBeEnabled());
  });

  it.each(["transparency", "tree"] as const)("blocks incomplete exports and retries a failed %s request", async (failedSource) => {
    if (failedSource === "transparency") {
      vi.mocked(scoringApi.getTransparency)
        .mockRejectedValueOnce(new Error("transparency unavailable"))
        .mockResolvedValueOnce({ rows: [], can_see_exemption_aggregates: false });
      vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
    } else {
      vi.mocked(scoringApi.getTransparency).mockResolvedValue({ rows: [], can_see_exemption_aggregates: false });
      vi.mocked(hierarchyApi.fetchFullTree)
        .mockRejectedValueOnce(new Error("hierarchy unavailable"))
        .mockResolvedValueOnce([]);
    }
    const writeFile = vi.mocked(XLSX.writeFile);
    renderWithProviders(<ExportPage />);
    fireEvent.click(checkboxAt(1));

    const alert = await screen.findByRole("alert");
    const buttons = screen.getAllByRole("button");
    const exportButton = buttons[buttons.length - 1];
    expect(exportButton).toBeDisabled();
    fireEvent.click(exportButton);
    expect(writeFile).not.toHaveBeenCalled();

    fireEvent.click(within(alert).getByRole("button"));
    await waitFor(() => {
      expect(scoringApi.getTransparency).toHaveBeenCalledTimes(failedSource === "transparency" ? 2 : 1);
      expect(hierarchyApi.fetchFullTree).toHaveBeenCalledTimes(failedSource === "tree" ? 2 : 1);
      expect(screen.getAllByRole("button").slice(-1)[0]).toBeEnabled();
    });

    fireEvent.click(screen.getAllByRole("button").slice(-1)[0]);
    await waitFor(() => expect(writeFile).toHaveBeenCalledTimes(1));
  });

  it("keeps all transparency rows in hierarchy order and exports complete sub-unit aggregates", async () => {
    const rootAlpha: NodeDTO = {
      id: "alpha",
      name: "Alpha",
      parent_id: null,
      level: "unit",
      commander_id: null,
      commander_name: null,
      path_ids: ["alpha"],
      duty_managers: [],
      dm_manageable: true,
      can_edit: false,
    };
    const childAlpha: NodeDTO = {
      ...rootAlpha,
      id: "alpha-child",
      name: "Alpha Child",
      parent_id: "alpha",
      path_ids: ["alpha", "alpha-child"],
    };
    const rootBeta: NodeDTO = {
      ...rootAlpha,
      id: "beta",
      name: "Beta",
      path_ids: ["beta"],
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue({
      rows: [
        transparencyRow("s-beta", "C. Beta", "beta", "Beta", { active_days: 30, cumulative_score: "30", score_per_day: "3.5", normalised_score: "6" }),
        transparencyRow("s-child", "B. Child", "alpha-child", "Alpha Child", { active_days: 20, cumulative_score: "20", score_per_day: "2.5", normalised_score: "4" }),
        transparencyRow("s-alpha", "A. Alpha", "alpha", "Alpha"),
        transparencyRow("s-unassigned", "Z. Unassigned", null, null),
      ],
      can_see_exemption_aggregates: false,
    });
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([rootAlpha, childAlpha, rootBeta]);
    const writeFile = vi.mocked(XLSX.writeFile);

    renderWithProviders(<ExportPage />);
    fireEvent.click(checkboxAt(1));
    fireEvent.click(checkboxAt(2));
    await waitFor(() => {
      expect(scoringApi.getTransparency).toHaveBeenCalledTimes(1);
      expect(hierarchyApi.fetchFullTree).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button")).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(writeFile).toHaveBeenCalledTimes(1));
    const [workbook] = writeFile.mock.calls[0];
    const transparencyRows = XLSX.utils.sheet_to_json<unknown[]>(workbook.Sheets.transparency, { header: 1 });
    expect(transparencyRows).toHaveLength(5);
    expect(transparencyRows.slice(1).map((row) => row[1])).toEqual([
      "A. Alpha",
      "B. Child",
      "C. Beta",
      "Z. Unassigned",
    ]);

    const subUnitRows = XLSX.utils.sheet_to_json<unknown[]>(workbook.Sheets.sub_units, { header: 1 });
    expect(subUnitRows.slice(1).map((row) => [row[0], row[1], row[6]])).toEqual([
      ["Alpha", 2, 4],
      ["Beta", 1, 3.5],
      ["Alpha Child", 1, 2.5],
    ]);
  });
});
