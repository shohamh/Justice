import type { ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, test, vi } from "vitest";
import * as calendarApi from "../api/calendar";
import * as calendarDataApi from "../api/calendarData";
import type { CalendarShift } from "../api/calendar";
import UnitCalendar, { filterCalendarShifts } from "./UnitCalendar";

const mocks = vi.hoisted(() => ({ t: (key: string) => key }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mocks.t }),
}));

const mockUseAuth = vi.fn(() => ({ user: null as { role?: string; is_commander?: boolean; is_duty_manager?: boolean } | null }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("../hooks/usePublicSettings", () => ({
  usePublicSettings: () => ({ "mitvachim.enabled": false }),
}));

vi.mock("../api/calendar", () => ({
  getCalendarShifts: vi.fn(),
  getCalendarWeaponIneligibleCount: vi.fn(),
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
        projected_valid_until: "2027-08-01",
        reason: null,
        duty_type_name: "Duty",
        start_date: "2026-08-01",
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

function renderCalendar(initialProps: { nodeId?: string; soldierId?: string; weaponIneligibleOnly?: boolean } = { nodeId: "node-1" }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const calendar = (props: { nodeId?: string; soldierId?: string; weaponIneligibleOnly?: boolean }) => (
    <QueryClientProvider client={queryClient}>
      <UnitCalendar {...props} />
    </QueryClientProvider>
  );
  const result = render(calendar(initialProps));
  return { ...result, rerenderCalendar: (props: { nodeId?: string; soldierId?: string; weaponIneligibleOnly?: boolean }) => result.rerender(calendar(props)) };
}

function loadCalendarWith(shifts: CalendarShift[]) {
  vi.mocked(calendarDataApi.loadCalendarData).mockResolvedValue({ calendar: { shifts }, ranges: [] });
}

describe("UnitCalendar eligibility warning", () => {
  test("shows the loaded unique warning count and interactive hover classes", async () => {
    loadCalendarWith([shift("warning", "guard", false)]);
    vi.mocked(calendarApi.getCalendarWeaponIneligibleCount).mockResolvedValue({ count: 2 });

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    expect(await screen.findByTestId("unit-calendar-weapon-warning")).toHaveTextContent("2");
    const event = screen.getByTestId("calendar-event-warning");
    expect(event).toHaveClass("cursor-pointer", "hover:brightness-110", "dark:hover:brightness-125");
  });

  test("hides the warning while its count is loading without blocking calendar events", async () => {
    loadCalendarWith([shift("loading", "guard", false)]);
    let resolveCount: ((value: { count: number }) => void) | undefined;
    vi.mocked(calendarApi.getCalendarWeaponIneligibleCount).mockReturnValue(
      new Promise((resolve) => { resolveCount = resolve; }),
    );

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    expect(await screen.findByTestId("calendar-event-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("unit-calendar-weapon-warning")).not.toBeInTheDocument();
    resolveCount?.({ count: 3 });
    expect(await screen.findByTestId("unit-calendar-weapon-warning")).toHaveTextContent("3");
  });

  test("hides a failed warning count without blocking calendar events", async () => {
    loadCalendarWith([shift("error", "guard", false)]);
    vi.mocked(calendarApi.getCalendarWeaponIneligibleCount).mockRejectedValue(new Error("count failed"));

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    expect(await screen.findByTestId("calendar-event-error")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByTestId("unit-calendar-weapon-warning")).not.toBeInTheDocument();
    });
  });

  test("ignores a stale warning count after the visible date range changes", async () => {
    loadCalendarWith([shift("stale", "guard", false)]);
    let resolveFirst: ((value: { count: number }) => void) | undefined;
    let resolveSecond: ((value: { count: number }) => void) | undefined;
    vi.mocked(calendarApi.getCalendarWeaponIneligibleCount)
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));
    fireEvent.click(screen.getByTestId("set-calendar-dates-next"));

    await act(async () => {
      resolveSecond?.({ count: 2 });
      await Promise.resolve();
    });
    expect(screen.getByTestId("unit-calendar-weapon-warning")).toHaveTextContent("2");
    await act(async () => {
      resolveFirst?.({ count: 1 });
      await Promise.resolve();
    });
    expect(screen.getByTestId("unit-calendar-weapon-warning")).toHaveTextContent("2");
  });

  test("clears a loaded warning count when the calendar scope changes", async () => {
    loadCalendarWith([shift("scope-change", "guard", false)]);
    vi.mocked(calendarApi.getCalendarWeaponIneligibleCount).mockResolvedValue({ count: 4 });

    const { rerenderCalendar } = renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));
    expect(await screen.findByTestId("unit-calendar-weapon-warning")).toHaveTextContent("4");

    rerenderCalendar({ nodeId: "node-2" });

    expect(screen.queryByTestId("unit-calendar-weapon-warning")).not.toBeInTheDocument();
  });

  test("ignores a pending warning count after the calendar scope changes", async () => {
    loadCalendarWith([shift("scope-race", "guard", false)]);
    let resolveCount: ((value: { count: number }) => void) | undefined;
    vi.mocked(calendarApi.getCalendarWeaponIneligibleCount).mockReturnValue(
      new Promise((resolve) => { resolveCount = resolve; }),
    );

    const { rerenderCalendar } = renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));
    rerenderCalendar({ nodeId: "node-2" });

    await act(async () => {
      resolveCount?.({ count: 7 });
      await Promise.resolve();
    });
    expect(screen.queryByTestId("unit-calendar-weapon-warning")).not.toBeInTheDocument();
  });

  test("keeps the duty-type filter visible when the calendar has no assignments", async () => {
    loadCalendarWith([]);
    vi.mocked(calendarApi.getCalendarWeaponIneligibleCount).mockResolvedValue({ count: 0 });

    renderCalendar();

    expect(screen.getByText("unit_calendar.duty_type_filter_label")).toBeInTheDocument();
  });
});

describe("UnitCalendar range eligibility info indicator", () => {
  test("shows an info indicator on the event tile when an assignee is covered by a planned range", async () => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager", is_commander: false, is_duty_manager: true } });
    loadCalendarWith([shiftWithPlannedRangeAssignee("planned")]);
    vi.mocked(calendarApi.getCalendarWeaponIneligibleCount).mockResolvedValue({ count: 0 });

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    expect(await screen.findByLabelText("range_qualification.calendarBadge.info")).toBeInTheDocument();
  });

  test("hides the info indicator from a plain soldier viewing the calendar", async () => {
    mockUseAuth.mockReturnValue({ user: { role: "soldier", is_commander: false, is_duty_manager: false } });
    loadCalendarWith([shiftWithPlannedRangeAssignee("planned-soldier")]);
    vi.mocked(calendarApi.getCalendarWeaponIneligibleCount).mockResolvedValue({ count: 0 });

    renderCalendar();
    fireEvent.click(screen.getByTestId("set-calendar-dates"));

    await screen.findByTestId("calendar-event-planned-soldier");
    expect(screen.queryByLabelText("range_qualification.calendarBadge.info")).not.toBeInTheDocument();
  });
});
