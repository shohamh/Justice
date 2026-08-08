import { describe, expect, test } from "vitest";
import type { CalendarShift } from "../api/calendar";
import { filterCalendarShifts } from "./UnitCalendar";

function shift(id: string, dutyTypeId: string, weaponIneligible: boolean): CalendarShift {
  return {
    id,
    duty_type_id: dutyTypeId,
    duty_type_name: "Duty",
    duty_type_color: "#000",
    duty_location_name: "Location",
    start_date: "2026-08-01",
    end_date: "2026-08-02",
    start_time: "08:00",
    end_time: "16:00",
    start_at: "2026-08-01T08:00:00",
    end_at: "2026-08-02T16:00:00",
    required_count: 1,
    assigned_count: 1,
    fill_status: "full",
    reserve_count: 0,
    assignees: [{
      assignment_id: `${id}-assignment`,
      soldier_id: `${id}-soldier`,
      soldier_name: "Soldier",
      hierarchy_label: null,
      is_reserve: false,
      profile_picture_url: null,
      dismissals: [],
      reserve_assignment_id: null,
      reserve_hierarchy_distance: null,
      called_up_from: null,
      called_up_to: null,
      primary_assignment_ids: [],
      hierarchy_path_ids: [],
      weapon_ineligible: weaponIneligible,
      weapon_ineligible_reason: weaponIneligible ? "reason" : null,
    }],
  };
}

describe("filterCalendarShifts", () => {
  test("keeps only shifts with weapon-ineligible assignees when the filter is active", () => {
    const shifts = [shift("eligible", "guard", false), shift("ineligible", "guard", true)];

    expect(filterCalendarShifts(shifts, ["guard"], true).map((item) => item.id)).toEqual(["ineligible"]);
  });

  test("preserves all duty-type-filtered shifts when the weapon filter is inactive", () => {
    const shifts = [shift("guard", "guard", false), shift("patrol", "patrol", true)];

    expect(filterCalendarShifts(shifts, ["guard", "patrol"], false).map((item) => item.id)).toEqual(["guard", "patrol"]);
  });
});
