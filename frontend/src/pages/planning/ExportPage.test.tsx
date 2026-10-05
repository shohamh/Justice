import { beforeEach, describe, test, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "../../i18n";
import { dfsOrder } from "./ExportPage";
import ExportPage from "./ExportPage";
import type { NodeDTO } from "../../api/hierarchy";
import * as hierarchyApi from "../../api/hierarchy";
import * as scoringApi from "../../api/scoring";
import * as exportsApi from "../../api/exports";
import type { TransparencyRow } from "../../api/scoring";
import { getTransparencyAuthorizationScope } from "../../api/auth";
import { queryKeys } from "../../queryKeys";

function renderWithProviders(
  ui: React.ReactElement,
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }),
) {
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function renderWithCachedEmptyHierarchyData() {
  const cachedUser = {
    id: "viewer-1",
    role: "admin",
    scope_root_ids: [],
    active_deputy_grants: [],
    hierarchy_node_id: null,
    is_commander: false,
    is_duty_manager: false,
  } as Parameters<typeof getTransparencyAuthorizationScope>[0];
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  const scope = getTransparencyAuthorizationScope(cachedUser);
  queryClient.setQueryData(queryKeys.transparencyExportForScope(scope), {
    rows: [],
    can_see_exemption_aggregates: false,
  });
  queryClient.setQueryData(queryKeys.hierarchyTreeForExport(scope), []);
  return renderWithProviders(<ExportPage />, queryClient);
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

vi.mock("../../api/scoring", () => ({ getTransparencyForExport: vi.fn().mockResolvedValue({ rows: [] }) }));
vi.mock("../../api/hierarchy", () => ({ fetchFullTreeForExport: vi.fn().mockResolvedValue([]) }));
vi.mock("../../api/exports", () => ({ exportPlanning: vi.fn().mockResolvedValue(undefined) }));
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

beforeEach(() => {
  vi.clearAllMocks();
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

  it("renders checkboxes for the new range sheets", async () => {
    renderWithProviders(<ExportPage />);
    await waitFor(() => screen.getByText("ייצוא"));
    expect(screen.getByLabelText(/מיקומי מטווח/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^מטווחים$/)).toBeInTheDocument();
    expect(screen.getByLabelText(/שיבוצי מטווח/)).toBeInTheDocument();
  });

  it("sends config and data selections with empty tables without loading hierarchy data", async () => {
    renderWithProviders(<ExportPage />);
    fireEvent.click(checkboxAt(3));
    fireEvent.click(screen.getByLabelText(/מיקומי מטווח/));
    fireEvent.click(screen.getByLabelText(/^חיילים$/));
    fireEvent.click(screen.getByLabelText(/שיבוצי מטווח/));
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(exportsApi.exportPlanning).toHaveBeenCalledTimes(1));
    expect(exportsApi.exportPlanning).toHaveBeenCalledWith({
      filename: "export.xlsx",
      tables: [],
      config_sheets: ["duty_types", "range_locations"],
      data_sheets: ["soldiers", "range_assignments"],
    });
    expect(scoringApi.getTransparencyForExport).not.toHaveBeenCalled();
    expect(hierarchyApi.fetchFullTreeForExport).not.toHaveBeenCalled();
  });

  it("does not request an export when no sheet is selected", async () => {
    renderWithProviders(<ExportPage />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByRole("button")).toBeEnabled());
    expect(exportsApi.exportPlanning).not.toHaveBeenCalled();
  });

  it.each([
    ["transparency", 1],
    ["sub-units", 2],
  ] as const)("loads both required payloads when %s is selected", async (_sheet, checkboxIndex) => {
    vi.mocked(scoringApi.getTransparencyForExport).mockResolvedValue({ rows: [], can_see_exemption_aggregates: false });
    vi.mocked(hierarchyApi.fetchFullTreeForExport).mockResolvedValue([]);
    renderWithProviders(<ExportPage />);
    fireEvent.click(checkboxAt(checkboxIndex));

    await waitFor(() => {
      expect(scoringApi.getTransparencyForExport).toHaveBeenCalledTimes(1);
      expect(hierarchyApi.fetchFullTreeForExport).toHaveBeenCalledTimes(1);
    });
  });

  it("does not reuse in-flight lenient transparency and tree reads for an export", async () => {
    let resolveLenientRows!: (value: { rows: TransparencyRow[] }) => void;
    let resolveLenientTree!: (value: NodeDTO[]) => void;
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const scope = getTransparencyAuthorizationScope({
      id: "viewer-1",
      role: "admin",
      scope_root_ids: [],
      active_deputy_grants: [],
      hierarchy_node_id: null,
      is_commander: false,
      is_duty_manager: false,
    } as Parameters<typeof getTransparencyAuthorizationScope>[0]);
    const lenientRows = queryClient.fetchQuery({
      queryKey: queryKeys.transparencyForScope(scope),
      queryFn: () => new Promise<{ rows: TransparencyRow[] }>((resolve) => { resolveLenientRows = resolve; }),
    });
    const lenientTree = queryClient.fetchQuery({
      queryKey: queryKeys.hierarchyTree(),
      queryFn: () => new Promise<NodeDTO[]>((resolve) => { resolveLenientTree = resolve; }),
    });
    vi.mocked(scoringApi.getTransparencyForExport).mockResolvedValue({ rows: [], can_see_exemption_aggregates: false });
    vi.mocked(hierarchyApi.fetchFullTreeForExport).mockResolvedValue([]);

    renderWithProviders(<ExportPage />, queryClient);
    fireEvent.click(checkboxAt(1));

    await waitFor(() => {
      expect(scoringApi.getTransparencyForExport).toHaveBeenCalledTimes(1);
      expect(hierarchyApi.fetchFullTreeForExport).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button")).toBeEnabled();
    });
    resolveLenientRows({ rows: [] });
    resolveLenientTree([]);
    await Promise.all([lenientRows, lenientTree]);
  });

  it("disables export until the selected transparency rows and hierarchy finish loading", async () => {
    let resolveRows!: (value: { rows: TransparencyRow[]; can_see_exemption_aggregates: boolean }) => void;
    vi.mocked(scoringApi.getTransparencyForExport).mockReturnValue(new Promise((resolve) => { resolveRows = resolve; }));
    vi.mocked(hierarchyApi.fetchFullTreeForExport).mockResolvedValue([]);
    const exportPlanning = vi.mocked(exportsApi.exportPlanning);
    renderWithProviders(<ExportPage />);
    fireEvent.click(checkboxAt(1));

    await waitFor(() => expect(scoringApi.getTransparencyForExport).toHaveBeenCalledTimes(1));
    const exportButton = screen.getByRole("button");
    expect(exportButton).toBeDisabled();
    fireEvent.click(exportButton);
    expect(exportPlanning).not.toHaveBeenCalled();

    resolveRows({ rows: [], can_see_exemption_aggregates: false });
    await waitFor(() => expect(exportButton).toBeEnabled());
  });

  it.each(["rows", "tree"] as const)("blocks incomplete exports and retries a malformed %s response", async (failedSource) => {
    if (failedSource === "rows") {
      vi.mocked(scoringApi.getTransparencyForExport)
        .mockRejectedValueOnce(new Error("Invalid transparency rows response"))
        .mockResolvedValueOnce({ rows: [], can_see_exemption_aggregates: false });
      vi.mocked(hierarchyApi.fetchFullTreeForExport).mockResolvedValue([]);
    } else {
      vi.mocked(scoringApi.getTransparencyForExport).mockResolvedValue({ rows: [], can_see_exemption_aggregates: false });
      vi.mocked(hierarchyApi.fetchFullTreeForExport)
        .mockRejectedValueOnce(new Error("Invalid hierarchy tree response"))
        .mockResolvedValueOnce([]);
    }
    const exportPlanning = vi.mocked(exportsApi.exportPlanning);
    renderWithCachedEmptyHierarchyData();
    fireEvent.click(checkboxAt(1));

    const alert = await screen.findByRole("alert");
    const buttons = screen.getAllByRole("button");
    const exportButton = buttons[buttons.length - 1];
    expect(exportButton).toBeDisabled();
    fireEvent.click(exportButton);
    expect(exportPlanning).not.toHaveBeenCalled();

    fireEvent.click(within(alert).getByRole("button"));
    await waitFor(() => {
      expect(scoringApi.getTransparencyForExport).toHaveBeenCalledTimes(failedSource === "rows" ? 2 : 1);
      expect(hierarchyApi.fetchFullTreeForExport).toHaveBeenCalledTimes(failedSource === "tree" ? 2 : 1);
      expect(screen.getAllByRole("button").slice(-1)[0]).toBeEnabled();
    });

    fireEvent.click(screen.getAllByRole("button").slice(-1)[0]);
    await waitFor(() => expect(exportPlanning).toHaveBeenCalledTimes(1));
  });

  it("sends localized matrices in hierarchy order and includes only selected sheet keys", async () => {
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
    vi.mocked(scoringApi.getTransparencyForExport).mockResolvedValue({
      rows: [
        transparencyRow("s-beta", "C. Beta", "beta", "Beta", { active_days: 30, cumulative_score: "30", score_per_day: "3.5", normalised_score: "6" }),
        transparencyRow("s-child", "B. Child", "alpha-child", "Alpha Child", { active_days: 20, cumulative_score: "20", score_per_day: "2.5", normalised_score: "4" }),
        transparencyRow("s-alpha", "A. Alpha", "alpha", "Alpha"),
        transparencyRow("s-unassigned", "Z. Unassigned", null, null),
      ],
      can_see_exemption_aggregates: false,
    });
    vi.mocked(hierarchyApi.fetchFullTreeForExport).mockResolvedValue([rootAlpha, childAlpha, rootBeta]);
    renderWithProviders(<ExportPage />);
    fireEvent.click(checkboxAt(1));
    fireEvent.click(checkboxAt(2));
    fireEvent.click(screen.getByLabelText(/סוגי תורנות/));
    fireEvent.click(screen.getByLabelText(/מיקומי מטווח/));
    fireEvent.click(screen.getByLabelText(/^חיילים$/));
    fireEvent.click(screen.getByLabelText(/שיבוצי מטווח/));
    await waitFor(() => {
      expect(scoringApi.getTransparencyForExport).toHaveBeenCalledTimes(1);
      expect(hierarchyApi.fetchFullTreeForExport).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button")).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => expect(exportsApi.exportPlanning).toHaveBeenCalledTimes(1));
    expect(exportsApi.exportPlanning).toHaveBeenCalledWith({
      filename: "export.xlsx",
      tables: [
        {
          sheet_name: "transparency",
          headers: [
            "יחידה / תת-יחידה", "שם", "יחידה", "תאריך הצטרפות", "ימים פעילים", "דרגה",
            "כמות משמרות", "ניקוד מצטבר", "ניקוד ליום", "ניקוד מנורמל",
          ],
          rows: [
            ["Alpha", "A. Alpha", "Alpha", "2026-01-01", 10, "", 2, 10, 1.5, 2],
            ["Alpha / Alpha Child", "B. Child", "Alpha Child", "2026-01-01", 20, "", 2, 20, 2.5, 4],
            ["Beta", "C. Beta", "Beta", "2026-01-01", 30, "", 2, 30, 3.5, 6],
            ["", "Z. Unassigned", "", "2026-01-01", 10, "", 2, 10, 1.5, 2],
          ],
        },
        {
          sheet_name: "sub_units",
          headers: [
            "יחידה", "כמות חיילים", "חיילים פעילים (%)", "ממוצע ימים פעילים", "ממוצע ניקוד לחייל",
            "ממוצע ניקוד לחייל פעיל", "ניקוד ליום (מסגרת)", "ניקוד מנורמל ממוצע",
          ],
          rows: [
            ["Alpha", 2, 100, 15, 15, 15, 4, 3],
            ["Beta", 1, 100, 30, 30, 30, 3.5, 6],
            ["Alpha Child", 1, 100, 20, 20, 20, 2.5, 4],
          ],
        },
      ],
      config_sheets: ["duty_types", "range_locations"],
      data_sheets: ["soldiers", "range_assignments"],
    });
  });

  it("shows an alert when the planning export request fails", async () => {
    vi.mocked(exportsApi.exportPlanning).mockRejectedValueOnce(new Error("request failed"));
    renderWithProviders(<ExportPage />);
    fireEvent.click(screen.getByLabelText(/סוגי תורנות/));
    fireEvent.click(screen.getByRole("button"));

    expect(await screen.findByRole("alert")).toHaveTextContent("הייצוא נכשל. נסה שוב.");
    expect(exportsApi.exportPlanning).toHaveBeenCalledTimes(1);
  });
});
