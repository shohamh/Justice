import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import UpcomingRangesWidget from "./UpcomingRangesWidget";
import { RangeEvent } from "../../api/ranges";
import { dateToLocalIso } from "../../utils/formatDate";

// Instants straddling local/UTC midnight (2026-10-09T21:30Z is already 2026-10-10 in Asia/Jerusalem).
const NOW_INSTANTS = ["2026-10-09T21:30:00Z", "2026-10-09T12:00:00Z", "2026-10-10T00:00:00Z"];

describe("UpcomingRangesWidget", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it.each(NOW_INSTANTS)("renders only future range events, sorted by date (now=%s)", (nowIso) => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(nowIso) });
    const today = new Date();
    const future1 = new Date(today);
    future1.setDate(future1.getDate() + 5);
    const future2 = new Date(today);
    future2.setDate(future2.getDate() + 2);
    const past = new Date(today);
    past.setDate(past.getDate() - 1);

    const ranges: RangeEvent[] = [
      { id: "1", hierarchy_node_id: "n1", range_type: "laser", date: dateToLocalIso(future1), location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [], assigned_to_me: true },
      { id: "2", hierarchy_node_id: "n1", range_type: "live", date: dateToLocalIso(future2), location: "מטווח ב", required_count: 1, reserve_count: 0, status: "planned", assignments: [], assigned_to_me: true },
      { id: "3", hierarchy_node_id: "n1", range_type: "alal", date: dateToLocalIso(past), location: "מטווח ג", required_count: 1, reserve_count: 0, status: "planned", assignments: [], assigned_to_me: true },
    ];

    render(<UpcomingRangesWidget ranges={ranges} onOpenRange={() => {}} />);

    expect(screen.queryByText("מטווח ג")).not.toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1); // skip header row
    expect(rows[0]).toHaveTextContent("מטווח ב");
    expect(rows[1]).toHaveTextContent("מטווח א");
  });

  it("renders only events assigned to the current soldier", () => {
    const ranges: RangeEvent[] = [
      { id: "assigned", hierarchy_node_id: "n1", range_type: "laser", date: "2099-01-01", location: "מוקצה לי", required_count: 1, reserve_count: 0, status: "planned", assignments: [], assigned_to_me: true },
      { id: "unassigned", hierarchy_node_id: "n1", range_type: "live", date: "2099-01-02", location: "לא מוקצה לי", required_count: 1, reserve_count: 0, status: "planned", assignments: [], assigned_to_me: false },
    ];

    render(<UpcomingRangesWidget ranges={ranges} onOpenRange={() => {}} />);

    expect(screen.getByText("מוקצה לי")).toBeInTheDocument();
    expect(screen.queryByText("לא מוקצה לי")).not.toBeInTheDocument();
  });

  it("renders range_type as a Hebrew label instead of raw English", () => {
    const ranges: RangeEvent[] = [
      { id: "1", hierarchy_node_id: "n1", range_type: "laser", date: "2099-01-01", location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [], assigned_to_me: true },
    ];

    render(<UpcomingRangesWidget ranges={ranges} onOpenRange={() => {}} />);

    expect(screen.getByText("מטווח לייזר")).toBeInTheDocument();
    expect(screen.queryByText("laser")).not.toBeInTheDocument();
  });

  it("renders the empty state instead of crashing when ranges is a malformed non-array", () => {
    // getRanges (api/ranges.ts) is currently an unguarded pass-through — this
    // defends the widget against a malformed API response reaching .filter().
    const malformed = { detail: "unexpected response" } as unknown as RangeEvent[];

    render(<UpcomingRangesWidget ranges={malformed} onOpenRange={() => {}} />);

    expect(screen.getByText("אין מטווחים קרובים")).toBeInTheDocument();
  });
});
