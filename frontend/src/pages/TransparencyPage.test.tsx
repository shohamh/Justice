import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import "../i18n";
import TransparencyPage from "./TransparencyPage";
import * as scoringApi from "../api/scoring";
import * as hierarchyApi from "../api/hierarchy";
import * as potentialApi from "../api/potential";
import type { TransparencyOut, TransparencyPageSummary, TransparencyRow } from "../api/scoring";
import type { NodeDTO } from "../api/hierarchy";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      {ui}
    </QueryClientProvider>
  );
}

function makeTree(nodeId: string, nodeName: string): NodeDTO[] {
  return [
    {
      id: nodeId,
      level: "unit",
      name: nodeName,
      parent_id: null,
      commander_id: null,
      commander_name: null,
      path_ids: [nodeId],
      duty_managers: [],
      dm_manageable: false,
    },
  ];
}

vi.mock("../api/scoring");
vi.mock("../api/hierarchy");
vi.mock("../api/potential");

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "viewer-1",
      role: "admin",
      is_commander: false,
      is_duty_manager: false,
      hierarchy_node_id: "node-1",
      scope_root_ids: ["node-1"],
      active_deputy_grants: [],
      can_view_transparency: true,
    },
    authScopeReady: true,
    refreshMe: vi.fn(),
  }),
}));

function makeRow(overrides: Partial<TransparencyRow> = {}): TransparencyRow {
  return {
    soldier_id: "s1",
    full_name: "חייל בדיקה",
    node_id: "node-1",
    node_name: "יחידה 1",
    enrolled_at: "2026-01-01",
    active_days: 10,
    shift_count: 2,
    rank: null,
    is_officer: false,
    service_type: "חובה",
    cumulative_score: "1.00",
    score_per_day: "0.10",
    normalised_score: "1.00",
    is_globally_exempted: false,
    burden_share: 0.1,
    c_over_d: 0,
    burden_share_offset_raw: 0,
    exemptions_display: "",
    exemptions_visible: true,
    exemptions: [],
    has_global_exemption: false,
    has_partial_exemption: false,
    has_temporary_exemption: false,
    ...overrides,
  };
}

beforeEach(() => {
  if (!HTMLElement.prototype.scrollTo) HTMLElement.prototype.scrollTo = vi.fn();
  vi.mocked(scoringApi.getTransparency).mockResolvedValue({ rows: [], can_see_exemption_aggregates: true });
  vi.mocked(scoringApi.getTransparencyPage).mockImplementation(async request => {
    const result = await scoringApi.getTransparency();
    const rows = [...result.rows];
    if (request.sort === "rank" && request.rankOrder) {
      const rankOrder = new Map(request.rankOrder.map((rank, index) => [rank, index]));
      rows.sort((left, right) =>
        (rankOrder.get(right.rank ?? "") ?? -1) - (rankOrder.get(left.rank ?? "") ?? -1)
        || left.soldier_id.localeCompare(right.soldier_id));
    } else {
      rows.sort((left, right) => {
        const leftValue = left[request.sort as keyof TransparencyRow];
        const rightValue = right[request.sort as keyof TransparencyRow];
        const compared = typeof leftValue === "number" && typeof rightValue === "number"
          ? leftValue - rightValue
          : String(leftValue ?? "").localeCompare(String(rightValue ?? ""), "he");
        return (request.descending ? -compared : compared) || left.soldier_id.localeCompare(right.soldier_id);
      });
    }
    const summary: TransparencyPageSummary = {
      row_count: rows.length,
      average_cumulative: 0,
      average_active_days: 0,
      average_score_per_day: 0,
      average_normalised: 0,
      burden_share_mean: null,
      burden_share_stddev: null,
      burden_share_cv: null,
      burden_share_min: null,
      burden_share_max: null,
      burden_share_offset_min: null,
      burden_share_offset_max: null,
    };
    return {
      items: rows.map((row, index) => ({ ...row, row_num: index + 1 })),
      next_cursor: null,
      has_more: false,
      summary,
      can_see_exemption_aggregates: result.can_see_exemption_aggregates,
    };
  });
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(scoringApi.getFairnessComponents).mockRejectedValue(new Error("not needed"));
  vi.mocked(potentialApi.getBurdenShareGap).mockResolvedValue([]);
});

describe("TransparencyPage hierarchy loading", () => {
  it("loads units only after the Soldiers unit filter opens and allows selecting a returned unit", async () => {
    vi.mocked(hierarchyApi.fetchFullTree).mockClear();
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue(makeTree("node-1", "Unit One"));

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);
    await screen.findByTestId("transparency-page");
    expect(hierarchyApi.fetchFullTree).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("transparency-unit-filter-toggle"));
    const unitFilter = await screen.findByTestId("transparency-unit-filter");
    await waitFor(() => expect(hierarchyApi.fetchFullTree).toHaveBeenCalledTimes(1));
    fireEvent.focus(unitFilter);
    fireEvent.click(await screen.findByRole("button", { name: "Unit One" }));

    expect(screen.getByText("Unit One")).toBeInTheDocument();
  });

  it("shows hierarchy loading and a retryable error when the unit filter opens", async () => {
    vi.mocked(hierarchyApi.fetchFullTree).mockClear();
    let rejectTree!: (reason: unknown) => void;
    vi.mocked(hierarchyApi.fetchFullTree).mockImplementationOnce(() => new Promise((_, reject) => { rejectTree = reject; }));

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);
    await screen.findByTestId("transparency-page");
    fireEvent.click(screen.getByTestId("transparency-unit-filter-toggle"));

    expect(await screen.findByTestId("transparency-tree-loading")).toBeInTheDocument();
    await act(async () => rejectTree(new Error("hierarchy unavailable")));
    expect(await screen.findByTestId("transparency-tree-error")).toBeInTheDocument();
  });

  it("offers a retry after the hierarchy request fails", async () => {
    vi.mocked(hierarchyApi.fetchFullTree).mockClear();
    vi.mocked(hierarchyApi.fetchFullTree)
      .mockRejectedValueOnce(new Error("hierarchy unavailable"))
      .mockResolvedValue(makeTree("node-1", "Unit One"));

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);
    await screen.findByTestId("transparency-page");
    fireEvent.click(screen.getByTestId("transparency-unit-filter-toggle"));

    expect(await screen.findByTestId("transparency-tree-error")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("transparency-tree-retry"));
    await waitFor(() => expect(hierarchyApi.fetchFullTree).toHaveBeenCalledTimes(2));
    expect(await screen.findByTestId("transparency-unit-filter")).toBeInTheDocument();
    fireEvent.focus(screen.getByTestId("transparency-unit-filter"));
    expect(await screen.findByRole("button", { name: "Unit One" })).toBeInTheDocument();
  });
});

describe("TransparencyPage 403 handling", () => {
  it("shows a permission message instead of the table when the transparency endpoint returns 403", async () => {
    const forbiddenError = Object.assign(new Error("Forbidden"), {
      isAxiosError: true,
      response: { status: 403, data: { detail: "transparency_hidden" } },
    });
    vi.mocked(scoringApi.getTransparency).mockRejectedValue(forbiddenError);

    renderWithProviders(<MemoryRouter initialEntries={["/transparency?tab=sub_units"]}><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText("אין לך הרשאה לצפות בדף זה")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("transparency-table")).not.toBeInTheDocument();
  });
});

describe("TransparencyPage exemptions column", () => {
  it("renders an exemption chip for a visible row", async () => {
    const out: TransparencyOut = {
      rows: [makeRow({
        exemptions: [
          { id: "e1", exemption_type_name: "מגבלה רפואית", is_global: false, start_date: "2026-01-01", end_date: "2026-08-15" },
        ],
      })],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText("מגבלה רפואית (עד 15.08.2026)")).toBeInTheDocument();
    });
  });

  it("renders חסוי for a redacted row", async () => {
    const out: TransparencyOut = {
      rows: [makeRow({ exemptions_display: "חסוי", exemptions_visible: false })],
      can_see_exemption_aggregates: false,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText("חסוי")).toBeInTheDocument();
    });
  });
});

describe("TransparencyPage default sort order", () => {
  it("defaults to load (burden_share) descending, not rank", async () => {
    const out: TransparencyOut = {
      rows: [
        makeRow({ soldier_id: "s-low", full_name: "חלק בנטל נמוך", burden_share: 0.1 }),
        makeRow({ soldier_id: "s-high", full_name: "חלק בנטל גבוה", burden_share: 0.9 }),
        makeRow({ soldier_id: "s-mid", full_name: "חלק בנטל בינוני", burden_share: 0.5 }),
      ],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    const table = await screen.findByTestId("transparency-table");
    await waitFor(() => {
      expect(table.querySelectorAll("tbody tr").length).toBe(3);
    });

    const rowTexts = Array.from(table.querySelectorAll("tbody tr")).map((r) => r.textContent ?? "");
    const highIdx = rowTexts.findIndex((t) => t.includes("חלק בנטל גבוה"));
    const midIdx = rowTexts.findIndex((t) => t.includes("חלק בנטל בינוני"));
    const lowIdx = rowTexts.findIndex((t) => t.includes("חלק בנטל נמוך"));
    expect(highIdx).toBeLessThan(midIdx);
    expect(midIdx).toBeLessThan(lowIdx);
  });
});

describe("TransparencyPage rank column sort (on header click)", () => {
  async function clickRankHeader() {
    const { default: he } = await import("../i18n/he.json");
    await act(async () => {
      fireEvent.click(screen.getByText(he.transparency.rank));
    });
  }

  it("shows senior ranks above junior ranks once the rank column is clicked", async () => {
    const out: TransparencyOut = {
      rows: [
        makeRow({ soldier_id: "s-segen-mishne", full_name: 'סג"ם בדיקה', rank: "סגמ", is_officer: true }),
        makeRow({ soldier_id: "s-aluf-mishne", full_name: 'אל"ם בדיקה', rank: "אלמ", is_officer: true }),
      ],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    const table = await screen.findByTestId("transparency-table");
    await waitFor(() => {
      expect(screen.getByText('אל"ם בדיקה')).toBeInTheDocument();
    });
    await clickRankHeader();

    await waitFor(() => {
      const rowTexts = Array.from(table.querySelectorAll("tbody tr")).map((r) => r.textContent ?? "");
      const alufIndex = rowTexts.findIndex((t) => t.includes('אל"ם בדיקה'));
      const segenIndex = rowTexts.findIndex((t) => t.includes('סג"ם בדיקה'));
      expect(alufIndex).toBeGreaterThanOrEqual(0);
      expect(segenIndex).toBeGreaterThanOrEqual(0);
      expect(alufIndex).toBeLessThan(segenIndex);
    });
  });

  it("sorts סג\"ם (with gershayim, as stored for some soldiers) above אל\"ם, not as an unmatched fallback rank", async () => {
    const out: TransparencyOut = {
      rows: [
        makeRow({ soldier_id: "s-segen-mishne", full_name: 'סג"ם בדיקה', rank: 'סג"ם', is_officer: true }),
        makeRow({ soldier_id: "s-aluf-mishne", full_name: 'אל"ם בדיקה', rank: "אלמ", is_officer: true }),
      ],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    const table = await screen.findByTestId("transparency-table");
    await waitFor(() => {
      expect(screen.getByText('אל"ם בדיקה')).toBeInTheDocument();
    });
    await clickRankHeader();

    await waitFor(() => {
      const rowTexts = Array.from(table.querySelectorAll("tbody tr")).map((r) => r.textContent ?? "");
      const alufIndex = rowTexts.findIndex((t) => t.includes('אל"ם בדיקה'));
      const segenIndex = rowTexts.findIndex((t) => t.includes('סג"ם בדיקה'));
      expect(alufIndex).toBeGreaterThanOrEqual(0);
      expect(segenIndex).toBeGreaterThanOrEqual(0);
      expect(alufIndex).toBeLessThan(segenIndex);
    });
  });

  it("sorts the entire rank hierarchy senior-first once clicked, not just a two-rank sample", async () => {
    // Full hierarchy, junior to senior, mirroring backend/app/services/eligibility.py's
    // ENLISTED_RANKS + OFFICER_RANKS order exactly (verified byte-for-byte against that
    // file). Listed here shuffled (not already in order) so a passing test can't be
    // satisfied by coincidental array order.
    const juniorToSenior = [
      "טוראי", "רבט", "סמל", "סמר", "רסל", "רסר", "רסמ", "רסב", "רנג",
      "קמא", "סגמ", "סגן", "קאב", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
    ];
    // Fully reversed (senior-to-junior) input order — deliberately the
    // opposite of the expected output, so a passing test can't be satisfied
    // by coincidental array order.
    const shuffled = [...juniorToSenior].reverse();
    const out: TransparencyOut = {
      rows: shuffled.map((rank, i) =>
        makeRow({ soldier_id: `s-${i}`, full_name: `חייל-${rank}-${i}`, rank, is_officer: true })
      ),
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    const table = await screen.findByTestId("transparency-table");
    const scrollRegion = table.parentElement?.querySelector<HTMLElement>('[role="region"]');
    if (!scrollRegion) throw new Error("Transparency table scroll region not found");
    Object.defineProperty(scrollRegion, "clientHeight", { configurable: true, value: 2000 });
    fireEvent(window, new Event("resize"));
    await waitFor(() => {
      expect(table.querySelectorAll("tbody tr").length).toBe(juniorToSenior.length);
    });
    await clickRankHeader();

    await waitFor(() => {
      const rowTexts = Array.from(table.querySelectorAll("tbody tr")).map((r) => r.textContent ?? "");
      const renderedRankOrder = juniorToSenior
        .map((rank) => rowTexts.findIndex((t) => t.includes(`חייל-${rank}-`)))
        .map((idx, originalJuniorToSeniorIndex) => ({ idx, rank: juniorToSenior[originalJuniorToSeniorIndex] }));

      // Senior-first means the LAST rank in juniorToSenior (רב אלוף) should have
      // the SMALLEST row index, and the FIRST rank (טוראי) the LARGEST.
      for (let i = 0; i < renderedRankOrder.length - 1; i++) {
        const moreJunior = renderedRankOrder[i];
        const moreSenior = renderedRankOrder[i + 1];
        expect(moreSenior.idx).toBeLessThan(moreJunior.idx);
      }
    });
  });
});

describe("TransparencyPage cumulative score column", () => {
  it("rounds the cumulative score to 3 decimal places", async () => {
    const out: TransparencyOut = {
      rows: [makeRow({ cumulative_score: "9.029999999999999" })],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText("חייל בדיקה")).toBeInTheDocument();
    });

    expect(screen.getAllByText("9.030").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("9.029999999999999")).not.toBeInTheDocument();
    expect(screen.queryByText((text) => text.includes("9.0299"))).not.toBeInTheDocument();
  });
});

describe("TransparencyPage sub-units exemption aggregates", () => {
  it("redacts the three aggregate columns as חסוי when can_see_exemption_aggregates is false", async () => {
    const row = makeRow({ node_id: "node-1", node_name: "יחידה 1" });
    const out: TransparencyOut = {
      rows: [row],
      can_see_exemption_aggregates: false,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue(makeTree("node-1", "יחידה 1"));
    vi.mocked(hierarchyApi.fetchFullTree).mockClear();

    renderWithProviders(
      <MemoryRouter initialEntries={["/transparency?tab=sub_units"]}>
        <SoldierModalProvider>
          <TransparencyPage />
        </SoldierModalProvider>
      </MemoryRouter>,
    );

    expect(hierarchyApi.fetchFullTree).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(screen.getByText("יחידה 1")).toBeInTheDocument();
    });

    const redacted = screen.getAllByText("חסוי");
    expect(redacted.length).toBeGreaterThanOrEqual(3);
  });

  it("shows real counts in the aggregate columns when can_see_exemption_aggregates is true", async () => {
    const row = makeRow({
      node_id: "node-1",
      node_name: "יחידה 1",
      has_global_exemption: true,
      has_partial_exemption: false,
      has_temporary_exemption: true,
    });
    const out: TransparencyOut = {
      rows: [row],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue(makeTree("node-1", "יחידה 1"));

    renderWithProviders(
      <MemoryRouter initialEntries={["/transparency?tab=sub_units"]}>
        <SoldierModalProvider>
          <TransparencyPage />
        </SoldierModalProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("יחידה 1")).toBeInTheDocument();
    });

    expect(screen.queryByText("חסוי")).not.toBeInTheDocument();
    const rowEl = screen.getByText("יחידה 1").closest("tr");
    expect(rowEl).not.toBeNull();
    expect(rowEl!.textContent).toContain("1");
    expect(rowEl!.textContent).toContain("0");
  });
});

describe("TransparencyPage required data load errors", () => {
  it("shows a load error banner when the transparency response is malformed (not a 403)", async () => {
    vi.mocked(scoringApi.getTransparency).mockRejectedValue(new Error("Invalid transparency response"));

    renderWithProviders(<MemoryRouter initialEntries={["/transparency?tab=sub_units"]}><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText("שגיאה בטעינת נתוני השקיפות")).toBeInTheDocument();
    });
    // Distinct from the 403 "no permission" message.
    expect(screen.queryByText("אין לך הרשאה לצפות בדף זה")).not.toBeInTheDocument();
  });

  it("shows a load error alert instead of a silent no-op when the burden-share breakdown fails to load", async () => {
    const out: TransparencyOut = {
      rows: [makeRow({ soldier_id: "s1", full_name: "חייל בדיקה", burden_share: 0.25 })],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);
    vi.mocked(scoringApi.getBurdenShareBreakdown).mockRejectedValue(new Error("Invalid burden-share breakdown response"));

    renderWithProviders(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    await screen.findByText("חייל בדיקה");
    const breakdownButton = await screen.findByTitle("לחץ לפירוט רבעוני");
    fireEvent.click(breakdownButton);

    await waitFor(() => {
      expect(screen.getByText("שגיאה בטעינת פירוט חלק בנטל")).toBeInTheDocument();
    });
  });
});
