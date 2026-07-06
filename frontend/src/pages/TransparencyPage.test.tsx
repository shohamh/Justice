import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import TransparencyPage from "./TransparencyPage";
import * as scoringApi from "../api/scoring";
import * as hierarchyApi from "../api/hierarchy";
import * as potentialApi from "../api/potential";
import type { TransparencyOut, TransparencyRow } from "../api/scoring";
import type { NodeDTO } from "../api/hierarchy";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";

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
  useAuth: () => ({ user: { id: "viewer-1", role: "admin" } }),
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
    effort_score: 0.1,
    c_over_d: 0,
    effort_offset_raw: 0,
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
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(scoringApi.getFairnessComponents).mockRejectedValue(new Error("not needed"));
  vi.mocked(potentialApi.getEffortGap).mockResolvedValue([]);
});

describe("TransparencyPage exemptions column", () => {
  it("renders the exemptions_display value for a visible row", async () => {
    const out: TransparencyOut = {
      rows: [makeRow({ exemptions_display: "מגבלה רפואית (חלקי, עד 15/08/2026)" })],
      can_see_exemption_aggregates: true,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    render(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText("מגבלה רפואית (חלקי, עד 15/08/2026)")).toBeInTheDocument();
    });
  });

  it("renders חסוי for a redacted row", async () => {
    const out: TransparencyOut = {
      rows: [makeRow({ exemptions_display: "חסוי", exemptions_visible: false })],
      can_see_exemption_aggregates: false,
    };
    vi.mocked(scoringApi.getTransparency).mockResolvedValue(out);

    render(<MemoryRouter><SoldierModalProvider><TransparencyPage /></SoldierModalProvider></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getByText("חסוי")).toBeInTheDocument();
    });
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

    render(
      <MemoryRouter initialEntries={["/transparency?tab=sub_units"]}>
        <SoldierModalProvider>
          <TransparencyPage />
        </SoldierModalProvider>
      </MemoryRouter>,
    );

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

    render(
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
