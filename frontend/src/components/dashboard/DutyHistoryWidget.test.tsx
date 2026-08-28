import { describe, it, expect, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import DutyHistoryWidget from "./DutyHistoryWidget";
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

function renderWidget(extra: Partial<React.ComponentProps<typeof DutyHistoryWidget>> = {}) {
  return render(
    <MemoryRouter>
      <DutyHistoryWidget
        duties={[]}
        typeNames={{}}
        locationNames={{}}
        myRow={null}
        allRows={[]}
        canViewTransparency={true}
        {...extra}
      />
    </MemoryRouter>
  );
}

describe("DutyHistoryWidget", () => {
  it("shows the transparency-page link when the user can view transparency", () => {
    renderWidget({ canViewTransparency: true });
    expect(screen.getByText("לדף השקיפות →")).toBeInTheDocument();
  });

  it("hides the transparency-page link when the user lacks permission", () => {
    renderWidget({ canViewTransparency: false });
    expect(screen.queryByText("לדף השקיפות →")).not.toBeInTheDocument();
  });

  it("shows the soldier's burden-share percentage and rank in the stat row", () => {
    renderWidget({ burdenShare: share(), burdenShareBreakdown: breakdown });
    expect(screen.getByText("34.2%")).toBeInTheDocument();
    expect(screen.getByText(/מקום 4 מתוך 12/)).toBeInTheDocument();
  });

  it("names the duty types the comparison group shares", () => {
    renderWidget({ burdenShare: share(), burdenShareBreakdown: breakdown });
    expect(screen.getByText(/שמירה/)).toBeInTheDocument();
    expect(screen.getByText(/מטבח/)).toBeInTheDocument();
  });

  it("shows the low-sample caveat only when the group is small", () => {
    const { rerender } = renderWidget({ burdenShare: share({ low_sample: true, group_size: 2 }), burdenShareBreakdown: breakdown });
    expect(screen.getByText(/פחות מ-3 חיילים/)).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <DutyHistoryWidget
          duties={[]} typeNames={{}} locationNames={{}} myRow={null} allRows={[]} canViewTransparency={true}
          burdenShare={share({ low_sample: false })} burdenShareBreakdown={breakdown}
        />
      </MemoryRouter>
    );
    expect(screen.queryByText(/פחות מ-3 חיילים/)).not.toBeInTheDocument();
  });

  it("shows an explanatory message instead of rank when the soldier has no comparison group", () => {
    renderWidget({ burdenShare: share({ has_group: false, burden_share: null, rank: null, group_size: null }), burdenShareBreakdown: breakdown });
    expect(screen.getByText(/אין קבוצת השוואה/)).toBeInTheDocument();
    expect(screen.queryByText(/מקום/)).not.toBeInTheDocument();
  });

  it("opens the burden-share breakdown modal when the detail button is clicked", async () => {
    renderWidget({ burdenShare: share(), burdenShareBreakdown: breakdown, soldierName: "דני כהן" });
    expect(screen.queryByText(/פירוט חישוב חלק בנטל/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("הצג פירוט חישוב"));
    expect(screen.getByText(/פירוט חישוב חלק בנטל — דני כהן/)).toBeInTheDocument();
  });

  it("renders the burden-share trend chart when breakdown quarters exist", () => {
    renderWidget({ burdenShare: share(), burdenShareBreakdown: breakdown });
    expect(screen.getByText("חלק בנטל לאורך זמן")).toBeInTheDocument();
  });
});
