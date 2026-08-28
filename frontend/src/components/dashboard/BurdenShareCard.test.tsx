import { describe, it, expect, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import BurdenShareCard from "./BurdenShareCard";
import type { BurdenShare, BurdenShareBreakdown } from "../../api/scoring";

beforeAll(() => {
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

function share(overrides: Partial<BurdenShare> = {}): BurdenShare {
  return {
    has_group: true,
    burden_share: 0.342,
    rank: 4,
    group_size: 12,
    duty_type_names: ["שמירה", "מטבח"],
    peer_scores: [0.5, 0.4, 0.342, 0.3, 0.2, 0.19, 0.18, 0.15, 0.12, 0.1, 0.08, 0.05],
    mean: 0.25,
    stddev: 0.13,
    cv: 0.52,
    low_sample: false,
    ...overrides,
  };
}

const breakdown: BurdenShareBreakdown = {
  quarters: [
    {
      quarter_start: "2026-01-01", quarter_end: "2026-03-31", quarter_label: "Q1 2026",
      soldier_score: "10", unit_score: "40", active_frac: "1", share: "0.25", weighted_share: "0.25",
      is_partial: false, adjustment_delta: "0", contributions: [],
    },
    {
      quarter_start: "2026-04-01", quarter_end: "2026-06-30", quarter_label: "Q2 2026",
      soldier_score: "14", unit_score: "40", active_frac: "0.8", share: "0.35", weighted_share: "0.28",
      is_partial: true, adjustment_delta: "0", contributions: [],
    },
  ],
  burden_share: "0.342", A_i: "10", W_i: "30",
};

describe("BurdenShareCard", () => {
  it("shows the soldier's percentage, rank, and comparison-group size", () => {
    render(<BurdenShareCard share={share()} breakdown={breakdown} />);
    expect(screen.getByText("34.2%")).toBeInTheDocument();
    expect(screen.getByText(/מקום 4 מתוך 12/)).toBeInTheDocument();
  });

  it("names the duty types the comparison group shares", () => {
    render(<BurdenShareCard share={share()} breakdown={breakdown} />);
    expect(screen.getByText(/שמירה/)).toBeInTheDocument();
    expect(screen.getByText(/מטבח/)).toBeInTheDocument();
  });

  it("shows the low-sample caveat only when the group is small", () => {
    const { rerender } = render(<BurdenShareCard share={share({ low_sample: true, group_size: 2 })} breakdown={breakdown} />);
    expect(screen.getByText(/פחות מ-3 חיילים/)).toBeInTheDocument();

    rerender(<BurdenShareCard share={share({ low_sample: false })} breakdown={breakdown} />);
    expect(screen.queryByText(/פחות מ-3 חיילים/)).not.toBeInTheDocument();
  });

  it("renders an explanatory message instead of the card when the soldier has no comparison group", () => {
    render(<BurdenShareCard share={share({ has_group: false, burden_share: null, rank: null, group_size: null })} breakdown={breakdown} />);
    expect(screen.getByText(/אין קבוצת השוואה/)).toBeInTheDocument();
    expect(screen.queryByText(/מקום/)).not.toBeInTheDocument();
  });

  it("reveals the quarterly breakdown table only after expanding", async () => {
    render(<BurdenShareCard share={share()} breakdown={breakdown} />);
    expect(screen.queryByText("Q1 2026")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("הצג פירוט חישוב"));
    expect(screen.getByText("Q1 2026")).toBeInTheDocument();
    expect(screen.getByText("Q2 2026")).toBeInTheDocument();
  });

  it("flags a partial quarter in the breakdown table", async () => {
    render(<BurdenShareCard share={share()} breakdown={breakdown} />);
    await userEvent.click(screen.getByText("הצג פירוט חישוב"));
    expect(screen.getByText("רבעון חלקי")).toBeInTheDocument();
  });
});
