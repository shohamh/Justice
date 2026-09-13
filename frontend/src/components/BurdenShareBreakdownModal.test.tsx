import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import BurdenShareBreakdownModal from "./BurdenShareBreakdownModal";
import { BurdenShareBreakdown, BurdenShareContribution } from "../api/scoring";

vi.mock("../hooks/useModalBackClose", () => ({ useModalBackClose: vi.fn() }));

function contribution(overrides: Partial<BurdenShareContribution> = {}): BurdenShareContribution {
  return {
    kind: "duty",
    label: "שמירות",
    detail: "",
    score: "1.000",
    start_date: null,
    end_date: null,
    days: 1,
    multiplier: "1.00",
    ...overrides,
  };
}

function breakdown(contributions: BurdenShareContribution[]): BurdenShareBreakdown {
  return {
    burden_share: "0.05",
    A_i: "1.000",
    W_i: "20.000",
    quarters: [
      {
        quarter_start: "2026-01-01",
        quarter_end: "2026-03-31",
        quarter_label: "Q1 2026",
        soldier_score: "1.000",
        unit_score: "20.000",
        active_frac: "1",
        share: "0.05",
        weighted_share: "0.05",
        is_partial: false,
        adjustment_delta: "0",
        contributions,
      },
    ],
  };
}

describe("BurdenShareBreakdownModal adjustment reason labels", () => {
  it("translates a known internal adjustment reason code instead of showing it raw", () => {
    render(
      <BurdenShareBreakdownModal
        soldierName="אורי"
        breakdown={breakdown([contribution({ kind: "adjustment", label: "range_no_show", score: "-1.000" })])}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("אי-הופעה למטווח")).toBeInTheDocument();
    expect(screen.queryByText("range_no_show")).not.toBeInTheDocument();
  });

  it("shows a free-text adjustment reason unchanged", () => {
    render(
      <BurdenShareBreakdownModal
        soldierName="אורי"
        breakdown={breakdown([contribution({ kind: "adjustment", label: "תיקון ידני לפי בקשת מפקד", score: "0.500" })])}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("תיקון ידני לפי בקשת מפקד")).toBeInTheDocument();
  });
});
