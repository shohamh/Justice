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

vi.mock("../api/calendarHolidays", () => ({
  listHolidays: vi.fn().mockResolvedValue([
    { date: "2026-09-11", name: "Eve of Rosh Hashanah" },
    { date: "2026-09-12", name: "Rosh Hashanah" },
  ]),
}));

vi.mock("@fullcalendar/react", () => ({
  default: ({ datesSet, events, eventContent, dayCellClassNames, eventClick }: {
    datesSet: (arg: unknown) => void;
    events: Array<{ id: string; title: string; classNames: string[]; extendedProps?: Record<string, unknown> }>;
    eventContent?: (arg: { event: { extendedProps: Record<string, unknown> } }) => ReactNode;
    dayCellClassNames?: (arg: { date: Date }) => string[];
    eventClick?: (arg: { event: { extendedProps: Record<string, unknown>; title: string; start: Date } }) => void;
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
      {["2026-08-01", "2026-09-12"].map((iso) => {
        const [year, month, day] = iso.split("-").map(Number);
        // Local-time midnight, matching how FullCalendar's default
        // timeZone: 'local' mode hands dates to dayCellClassNames — NOT
        // UTC midnight, which would mask a UTC-conversion bug in timezones
        // ahead of UTC (e.g. Asia/Jerusalem, this app's primary locale).
        return (
          <div
            key={iso}
            data-testid={`day-cell-${iso}`}
            data-date={iso}
            className={(dayCellClassNames?.({ date: new Date(year, month - 1, day) }) ?? []).join(" ")}
          />
        );
      })}
      {events.map((event) => (
        <button
          key={event.id}
          data-testid={`calendar-event-${event.id}`}
          className={event.classNames.join(" ")}
          onClick={() => eventClick?.({ event: { extendedProps: event.extendedProps ?? {}, title: event.title, start: new Date(`${event.id.slice(-10)}T00:00:00`) } })}
        >
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
    crossed_holidays: [],
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
    crossed_holidays: [],
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

type CalendarProps = { nodeId?: string; nodeIds?: string[]; soldierId?: string; scope?: "personal" | "command" };

function renderCalendar(initialProps: CalendarProps = { nodeId: "node-1" }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const calendar = (props: CalendarProps) => (
    <QueryClientProvider client={queryClient}>
      <UnitCalendar {...props} />
    </QueryClientProvider>
  );
  const result = render(calendar(initialProps));
  return { ...result, rerenderCalendar: (props: CalendarProps) => result.rerender(calendar(props)) };
}

function loadCalendarWith(shifts: CalendarShift[]) {
  vi.mocked(calendarDataApi.loadCalendarData).mockResolvedValue({ calendar: { shifts }, ranges: [] });
}

describe("UnitCalendar", () => {
  test("renders a command scope label only when the parent explicitly requests command scope", () => {
    loadCalendarWith([]);

    renderCalendar({ nodeIds: ["node-1"], scope: "command" });

    expect(screen.getByTestId("unit-calendar-scope-label")).toHaveTextContent("unit_calendar.scope_command");
  });

  test("renders a personal scope label only when the parent explicitly requests personal scope", () => {
    loadCalendarWith([]);

    renderCalendar({ soldierId: "soldier-1", scope: "personal" });

    expect(screen.getByTestId("unit-calendar-scope-label")).toHaveTextContent("unit_calendar.scope_personal");
  });

  test("does not infer a scope label from a soldier-filtered calendar", () => {
    loadCalendarWith([]);

    renderCalendar({ soldierId: "soldier-1" });

    expect(screen.queryByTestId("unit-calendar-scope-label")).not.toBeInTheDocument();
  });

  test("keeps the duty-type filter visible when the calendar has no assignments", async () => {
    loadCalendarWith([]);

    renderCalendar();

    expect(screen.getByText("unit_calendar.duty_type_filter_label")).toBeInTheDocument();
  });

  test("merges shifts from multiple commanded nodes and dedupes overlapping ids", async () => {
    const perNodeResults = [
      { calendar: { shifts: [shift("s1", "guard", false)] }, ranges: [] },
      { calendar: { shifts: [shift("s1", "guard", false), shift("s2", "patrol", false)] }, ranges: [] },
    ];
    let call = 0;
    vi.mocked(calendarDataApi.loadCalendarData).mockImplementation(() => Promise.resolve(perNodeResults[call++]));

    renderCalendar({ nodeIds: ["node-1", "node-2"] });
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    expect(await screen.findByTestId("calendar-event-s1")).toBeInTheDocument();
    expect(screen.getByTestId("calendar-event-s2")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^calendar-event-s\d$/)).toHaveLength(2);
    expect(calendarDataApi.loadCalendarData).toHaveBeenCalledTimes(2);
  });

  // getCalendarShifts (via loadCalendarData) throws a descriptive error for a
  // malformed calendar payload — the calendar must surface that failure as an
  // accessible alert rather than a silent gap in the grid.
  test("shows an accessible error alert when the calendar data fails to load", async () => {
    vi.mocked(calendarDataApi.loadCalendarData).mockRejectedValue(new Error("Invalid calendar shifts response"));

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("unit_calendar.error");
    expect(alert).toBe(screen.getByTestId("unit-calendar-error"));
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

describe("UnitCalendar holidays", () => {
  afterEach(() => {
    vi.mocked(useAuth).mockReturnValue({ user: null } as ReturnType<typeof useAuth>);
  });

  test("applies a holiday day-cell class to a known holiday date", async () => {
    loadCalendarWith([]);

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    await waitFor(() => {
      const cell = document.querySelector('[data-date="2026-09-12"]');
      expect(cell?.className).toMatch(/holiday-day-cell/);
    });
  });

  test("shows a holiday badge on a shift event that crosses a holiday", async () => {
    const testShift: CalendarShift = {
      ...shift("holiday-shift", "guard", false),
      crossed_holidays: [{ date: "2026-09-12", name: "Rosh Hashanah" }],
    };
    loadCalendarWith([testShift]);

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    await waitFor(() => {
      expect(screen.getByTestId(`shift-holiday-badge-${testShift.id}`)).toBeInTheDocument();
    });
  });

  test("renders holiday events before duties with the holiday name and special styling", async () => {
    const testShift = shift("holiday-order-shift", "guard", false);
    loadCalendarWith([testShift]);

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    const holidayEvent = await screen.findByTestId("calendar-event-holiday-2026-09-12");
    expect(holidayEvent).toHaveTextContent("✡️ Rosh Hashanah");
    expect(holidayEvent.className).toMatch(/holiday-calendar-event/);
    expect(holidayEvent.className).toMatch(/holiday-sparkle-border/);
    expect(holidayEvent.compareDocumentPosition(screen.getByTestId(`calendar-event-${testShift.id}`)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("can hide and show holiday events with the holiday filter", async () => {
    loadCalendarWith([]);

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));
    await screen.findByTestId("calendar-event-holiday-2026-09-12");

    fireEvent.click(screen.getByLabelText("unit_calendar.show_holidays"));
    expect(screen.queryByTestId("calendar-event-holiday-2026-09-12")).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("unit_calendar.show_holidays"));
    expect(await screen.findByTestId("calendar-event-holiday-2026-09-12")).toBeInTheDocument();
  });

  test("opens holiday details when the holiday event is clicked", async () => {
    loadCalendarWith([]);

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));
    const holidayEvent = await screen.findByTestId("calendar-event-holiday-2026-09-12");
    fireEvent.click(holidayEvent);

    expect(await screen.findByRole("dialog")).toHaveTextContent("Rosh Hashanah");
    expect(screen.getByRole("dialog")).toHaveTextContent("12.09.2026");
  });

  test("renders the eve of a holiday as its own calendar event", async () => {
    loadCalendarWith([]);

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    expect(await screen.findByTestId("calendar-event-holiday-2026-09-11")).toHaveTextContent("Eve of Rosh Hashanah");
  });
});
