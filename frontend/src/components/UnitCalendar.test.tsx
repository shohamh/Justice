import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, test, vi } from "vitest";
import * as calendarDataApi from "../api/calendarData";
import type { CalendarShift, CalendarShiftAssignee } from "../api/calendar";
import { useAuth } from "../auth/AuthContext";
import UnitCalendar, { filterCalendarShifts } from "./UnitCalendar";

const mocks = vi.hoisted(() => ({ t: (key: string) => key }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mocks.t }),
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: vi.fn(() => ({ user: null })),
}));

vi.mock("../hooks/usePublicSettings", () => ({
  usePublicSettings: () => ({ "mitvachim.enabled": false }),
}));

vi.mock("../api/calendar", () => ({
  getCalendarShifts: vi.fn(),
}));

vi.mock("../api/calendarData", () => ({
  loadCalendarData: vi.fn(),
}));

vi.mock("@fullcalendar/react", () => ({
  default: ({ datesSet, events, eventContent }: {
    datesSet: (arg: unknown) => void;
    events: Array<{ id: string; title: string; classNames: string[]; extendedProps?: Record<string, unknown> }>;
    eventContent?: (arg: { event: { extendedProps: Record<string, unknown> } }) => ReactNode;
  }) => (
    <div>
      <button
        data-testid="set-calendar-dates"
        onClick={() => datesSet({
          start: new Date("2026-08-01T00:00:00Z"),
          end: new Date("2026-08-08T00:00:00Z"),
          view: { type: "dayGridMonth" },
        })}
      >
        set dates
      </button>
      <button
        data-testid="set-calendar-dates-next"
        onClick={() => datesSet({
          start: new Date("2026-08-08T00:00:00Z"),
          end: new Date("2026-08-15T00:00:00Z"),
          view: { type: "dayGridMonth" },
        })}
      >
        set next dates
      </button>
      {events.map((event) => (
        <button key={event.id} data-testid={`calendar-event-${event.id}`} className={event.classNames.join(" ")}>
          {event.title}
          {eventContent && eventContent({ event: { extendedProps: event.extendedProps ?? {} } })}
        </button>
      ))}
    </div>
  ),
}));

function shift(
  id: string,
  dutyTypeId: string,
  weaponIneligible: boolean,
  assigneeOverrides: Partial<CalendarShiftAssignee> = {},
): CalendarShift {
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
      range_eligibility: null,
      ...assigneeOverrides,
    }],
  };
}

function shiftWithPlannedRangeAssignee(id: string): CalendarShift {
  return {
    id,
    duty_type_id: "guard",
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
      weapon_ineligible: false,
      weapon_ineligible_reason: null,
      range_eligibility: {
        eligible: true,
        required_range_type: "laser",
        qualification_source: "planned_range",
        covered_by_range_date: "2026-08-01",
        covering_range_type: "laser",
        projected_valid_until: "2027-08-01",
        reason: null,
        duty_type_name: "Duty",
        start_date: "2026-08-01",
        last_qualification_type: null,
        last_qualification_date: null,
      },
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

function renderCalendar(initialProps: { nodeId?: string; soldierId?: string } = { nodeId: "node-1" }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const calendar = (props: { nodeId?: string; soldierId?: string }) => (
    <QueryClientProvider client={queryClient}>
      <UnitCalendar {...props} />
    </QueryClientProvider>
  );
  const result = render(calendar(initialProps));
  return { ...result, rerenderCalendar: (props: { nodeId?: string; soldierId?: string }) => result.rerender(calendar(props)) };
}

function loadCalendarWith(shifts: CalendarShift[]) {
  vi.mocked(calendarDataApi.loadCalendarData).mockResolvedValue({ calendar: { shifts }, ranges: [] });
}

describe("UnitCalendar", () => {
  test("keeps the duty-type filter visible when the calendar has no assignments", async () => {
    loadCalendarWith([]);

    renderCalendar();

    expect(screen.getByText("unit_calendar.duty_type_filter_label")).toBeInTheDocument();
  });
});

describe("UnitCalendar range eligibility info indicator", () => {
  afterEach(() => {
    vi.mocked(useAuth).mockReturnValue({ user: null } as ReturnType<typeof useAuth>);
  });

  test("shows an info indicator on the event tile when an assignee is covered by a planned range", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { role: "duty_manager", is_commander: false, is_duty_manager: true },
    } as ReturnType<typeof useAuth>);
    loadCalendarWith([shiftWithPlannedRangeAssignee("planned")]);

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    expect(await screen.findByLabelText("range_qualification.calendarBadge.info")).toBeInTheDocument();
  });

  test("hides the info indicator from a plain soldier viewing the calendar", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { role: "soldier", is_commander: false, is_duty_manager: false },
    } as ReturnType<typeof useAuth>);
    loadCalendarWith([shiftWithPlannedRangeAssignee("planned-soldier")]);

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    await screen.findByTestId("calendar-event-planned-soldier");
    expect(screen.queryByLabelText("range_qualification.calendarBadge.info")).not.toBeInTheDocument();
  });
});

describe("UnitCalendar eligibility badges", () => {
  afterEach(() => {
    vi.mocked(useAuth).mockReturnValue({ user: null } as ReturnType<typeof useAuth>);
  });

  test("shows a warning badge on the event when an assignee is weapon-ineligible, for duty managers", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { role: "soldier", is_duty_manager: true, is_commander: false },
    } as ReturnType<typeof useAuth>);
    const testShift = shift("warn-shift", "guard", true, {
      range_eligibility: {
        eligible: false, required_range_type: "alal", qualification_source: null,
        covered_by_range_date: null, covering_range_type: null, projected_valid_until: null,
        reason: "weapon_qualification", duty_type_name: "alal-duty", start_date: "2026-11-11",
        last_qualification_type: null, last_qualification_date: null,
      },
    });
    loadCalendarWith([testShift]);

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    await waitFor(() => screen.getByTestId(`shift-warning-badge-${testShift.id}`));

    expect(screen.getByTestId(`shift-warning-badge-${testShift.id}`)).toBeInTheDocument();
  });

  test("does not show badges for a plain soldier", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { role: "soldier", is_duty_manager: false, is_commander: false },
    } as ReturnType<typeof useAuth>);
    const testShift = shift("plain-shift", "guard", true, { range_eligibility: null });
    loadCalendarWith([testShift]);

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    await waitFor(() => screen.getByTestId(`calendar-event-${testShift.id}`));

    expect(screen.queryByTestId(`shift-warning-badge-${testShift.id}`)).not.toBeInTheDocument();
  });
});
vi.mock('../api/ranges', () => ({
  getRanges: vi.fn(() => Promise.resolve([])),
  getMyRanges: vi.fn(() => Promise.resolve([])),
}));
vi.mock('../api/dutyConfig', () => ({
  listDutyTypes: vi.fn(() => Promise.resolve([])),
}));
