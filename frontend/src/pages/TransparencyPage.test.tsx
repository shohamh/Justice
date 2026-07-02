import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import TransparencyPage from "./TransparencyPage";
import * as scoringApi from "../api/scoring";
import * as hierarchyApi from "../api/hierarchy";
import type { TransparencyOut, TransparencyRow } from "../api/scoring";
import { SoldierModalProvider } from "../contexts/SoldierModalContext";

vi.mock("../api/scoring");
vi.mock("../api/hierarchy");

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
    has_global_exemption: false,
    has_partial_exemption: false,
    has_temporary_exemption: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue([]);
  vi.mocked(scoringApi.getFairnessComponents).mockRejectedValue(new Error("not needed"));
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
