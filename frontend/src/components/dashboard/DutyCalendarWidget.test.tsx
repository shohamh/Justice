import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import DutyCalendarWidget from "./DutyCalendarWidget";

describe("DutyCalendarWidget", () => {
  it("shows the duty's own name even when typeNames lookup is empty", () => {
    const duty = {
      assignment_id: "a1", soldier_id: "s1", duty_type_id: "missing-id",
      duty_type_name: "שמירה ראשית", duty_location_id: "l1",
      start_date: "2026-08-01", end_date: "2026-08-01",
      start_time: "08:00", end_time: "20:00",
      start_at: "2026-08-01T08:00:00Z", end_at: "2026-08-01T20:00:00Z",
      is_reserve: false,
    };
    const { container } = render(
      <DutyCalendarWidget duties={[duty]} typeNames={{}} onOpenDuty={() => {}} />
    );
    expect(container.textContent).toContain("שמירה ראשית");
    expect(container.textContent).not.toContain("תורנות");
  });

  it("renders range events distinctly from duty events", () => {
    const ranges = [
      { id: "r1", hierarchy_node_id: "n1", range_type: "laser" as const, date: "2026-09-01",
        location: "מטווח דרום", required_count: 3, reserve_count: 1, status: "planned" as const, assignments: [] },
    ];

    const { container } = render(
      <DutyCalendarWidget duties={[]} typeNames={{}} onOpenDuty={() => {}} ranges={ranges} onOpenRange={() => {}} />,
    );

    expect(container.textContent).toContain("מטווח דרום");
  });
});
