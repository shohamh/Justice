import { describe, it, expect, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import BurdenShareTrendChart from "./BurdenShareTrendChart";
import type { BurdenShareQuarterRow } from "../../api/scoring";

beforeAll(() => {
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

function quarter(overrides: Partial<BurdenShareQuarterRow> = {}): BurdenShareQuarterRow {
  return {
    quarter_start: "2026-01-01", quarter_end: "2026-03-31", quarter_label: "Q1 2026",
    soldier_score: "10", unit_score: "40", active_frac: "1", share: "0.25", weighted_share: "0.25",
    is_partial: false, adjustment_delta: "0", contributions: [],
    ...overrides,
  };
}

describe("BurdenShareTrendChart", () => {
  it("shows the empty-state message when there are no quarters", () => {
    render(<BurdenShareTrendChart quarters={[]} />);
    expect(screen.getByText("אין עדיין נתוני מגמה")).toBeInTheDocument();
  });

  it("renders a chart when at least one quarter exists", () => {
    render(<BurdenShareTrendChart quarters={[quarter()]} />);
    expect(screen.queryByText("אין עדיין נתוני מגמה")).not.toBeInTheDocument();
  });
});
