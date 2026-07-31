import { describe, it, expect, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import DutyTypeBreakdownChart from "./DutyTypeBreakdownChart";

// recharts' ResponsiveContainer measures its container via ResizeObserver, which
// jsdom does not implement. Without a stub, recharts silently renders a 0x0 chart
// (or throws in some versions) — a no-op stub is enough since we only assert on
// text content, not pixel dimensions.
beforeAll(() => {
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

describe("DutyTypeBreakdownChart", () => {
  it("shows the empty-state message when there is no data with days > 0", () => {
    render(<DutyTypeBreakdownChart perType={[]} />);
    expect(screen.getByText("אין נתוני פירוט")).toBeInTheDocument();
  });

  it("filters out entries with 0 total days", () => {
    render(
      <DutyTypeBreakdownChart
        perType={[
          { duty_type_id: "1", duty_type_name: "שמירה", days: 0, days_past: 0, days_future: 0, score: "0" },
        ]}
      />
    );
    expect(screen.getByText("אין נתוני פירוט")).toBeInTheDocument();
  });

  it("renders a chart when at least one entry has days > 0", () => {
    render(
      <DutyTypeBreakdownChart
        perType={[
          { duty_type_id: "1", duty_type_name: "שמירה", days: 3, days_past: 2, days_future: 1, score: "10" },
        ]}
      />
    );
    expect(screen.queryByText("אין נתוני פירוט")).not.toBeInTheDocument();
  });
});
