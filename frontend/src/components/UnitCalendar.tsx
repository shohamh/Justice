import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { ArrowLeftRight } from "lucide-react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import heLocale from "@fullcalendar/core/locales/he";
import type { EventClickArg, DatesSetArg } from "@fullcalendar/core";

import { CalendarShift, getCalendarShifts } from "../api/calendar";
import { loadCalendarData } from "../api/calendarData";
import { RangeEvent, getRanges, getMyRanges } from "../api/ranges";
import { listDutyTypes } from "../api/dutyConfig";
import { RANGE_TYPE_LABELS } from "../utils/rangeLabels";
import { usePublicSettings } from "../hooks/usePublicSettings";
import { useAuth } from "../auth/AuthContext";
import { canApprove } from "../auth/permissions";
import { formatDate, formatRangeEligibilityExplanation } from "../utils/rangeEligibilityExplanation";
import ShiftDetailPanel from "./ShiftDetailPanel";
import RangeDetailModal from "./ranges/RangeDetailModal";
import { calendarViewMinWidth } from "../utils/calendarViewWidth";
import { shiftToCalendarEvent, shiftSpansMultipleDays, shiftEdgeLabels } from "../utils/shiftCalendarEvent";
import CheckboxListDropdown from "./CheckboxListDropdown";

const RANGE_TYPE_COLORS: Record<string, string> = {
  laser: "#7c3aed",
  live: "#db2777",
  alal: "#0891b2",
};

const CALENDAR_EVENT_INTERACTION_CLASSES = [
  "cursor-pointer",
  "transition",
  "hover:brightness-110",
  "dark:hover:brightness-125",
];


interface UnitCalendarProps {
  // Node whose subtree to show. Required unless soldierId is given.
  nodeId?: string;
  // When set, shows only this soldier's own duties/ranges (personal view) —
  // both shifts and ranges are fetched by soldier, ignoring nodeId/hierarchy
  // entirely (a duty or range can involve a soldier outside its own node's
  // subtree, e.g. as a reserve or a cross-unit range assignment).
  soldierId?: string;
}

export function filterCalendarShifts(
  shifts: CalendarShift[],
  dutyTypeIds: string[],
  weaponIneligibleOnly: boolean,
): CalendarShift[] {
  return shifts.filter(
    (shift) =>
      dutyTypeIds.includes(shift.duty_type_id) &&
      (!weaponIneligibleOnly || shift.assignees.some((assignee) => assignee.weapon_ineligible)),
  );
}

export default function UnitCalendar({ nodeId, soldierId }: UnitCalendarProps) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const canSeeEligibilityBadges = canApprove(user);
  const publicSettings = usePublicSettings();
  const rangesEnabled = publicSettings?.["mitvachim.enabled"] === true;
  const [shifts, setShifts] = useState<CalendarShift[]>([]);
  const [ranges, setRanges] = useState<RangeEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedShift, setSelectedShift] = useState<CalendarShift | null>(null);
  const [selectedRangeId, setSelectedRangeId] = useState<string | null>(null);
  // null means "no manual selection yet" — everything currently known is
  // treated as selected. Once the user touches the dropdown, this becomes a
  // concrete array reflecting exactly what's checked, including an empty
  // array (meaning "show nothing of this category"), not "no filter".
  const [dutyTypeFilter, setDutyTypeFilter] = useState<string[] | null>(null);
  const [rangeTypeFilter, setRangeTypeFilter] = useState<string[] | null>(null);
  const [activeViewType, setActiveViewType] = useState("dayGridMonth");
  const [allDutyTypes, setAllDutyTypes] = useState<{ id: string; name: string }[]>([]);

  const dateRangeRef = useRef<{ from: string; to: string } | null>(null);

  const fetchData = useCallback(async (from: string, to: string) => {
    if (!nodeId && !soldierId) return;
    setLoading(true);
    setError(null);
    try {
      const { calendar, ranges: rangeEvents } = await loadCalendarData(
        () => getCalendarShifts({ nodeId: soldierId ? undefined : nodeId, soldierId, date_from: from, date_to: to }),
        () => (soldierId ? getMyRanges(soldierId, from, to) : (nodeId ? getRanges(nodeId, from, to) : Promise.resolve([]))),
        rangesEnabled,
      );
      setShifts(calendar.shifts);
      setRanges(rangeEvents);
      setSelectedShift(prev => {
        if (!prev) return null;
        return calendar.shifts.find(s => s.id === prev.id) ?? prev;
      });
    } catch {
      setError(t("unit_calendar.error") || "Failed to load calendar");
    } finally {
      setLoading(false);
    }
  }, [nodeId, soldierId, rangesEnabled, t]);

  useEffect(() => {
    dateRangeRef.current = null;
    setShifts([]);
    setRanges([]);
    setSelectedShift(null);
  }, [nodeId, soldierId]);

  // The duty-type filter should list every active duty type, not just the
  // ones that happen to have a shift in the currently-loaded date range —
  // a personal (soldierId) view can easily have zero shifts visible.
  useEffect(() => {
    listDutyTypes()
      .then(types => setAllDutyTypes(types.filter(dt => dt.active).map(dt => ({ id: dt.id, name: dt.name }))))
      .catch(() => setAllDutyTypes([]));
  }, []);

  // rangesEnabled starts out false/unknown until usePublicSettings resolves,
  // which usually happens after FullCalendar's initial datesSet already ran
  // and fetched with ranges disabled. Since datesSet won't fire again unless
  // the visible range changes, catch the flip to enabled here and refetch.
  useEffect(() => {
    const r = dateRangeRef.current;
    if (r) fetchData(r.from, r.to);
  }, [rangesEnabled, fetchData]);

  function handleDatesSet(arg: DatesSetArg) {
    setActiveViewType(arg.view.type);
    const from = arg.start.toISOString().slice(0, 10);
    const to = arg.end.toISOString().slice(0, 10);
    const prev = dateRangeRef.current;
    if (prev && prev.from === from && prev.to === to) return;
    dateRangeRef.current = { from, to };
    fetchData(from, to);
  }

  const dutyTypesInView = useMemo(() => {
    if (allDutyTypes.length > 0) return allDutyTypes;
    const seen = new Map<string, string>();
    for (const s of shifts) {
      if (!seen.has(s.duty_type_id)) seen.set(s.duty_type_id, s.duty_type_name);
    }
    return Array.from(seen.entries()).map(([id, name]) => ({ id, name }));
  }, [allDutyTypes, shifts]);

  const rangeTypeOptions = useMemo(
    () => Object.entries(RANGE_TYPE_LABELS).map(([id, name]) => ({ id, name })),
    [],
  );

  // Effective selection for both filtering and the dropdown's checked state:
  // before any manual interaction (null), everything currently known counts
  // as selected, so the calendar shows everything by default.
  const effectiveDutyTypeFilter = useMemo(
    () => dutyTypeFilter ?? dutyTypesInView.map(dt => dt.id),
    [dutyTypeFilter, dutyTypesInView],
  );
  const effectiveRangeTypeFilter = useMemo(
    () => rangeTypeFilter ?? rangeTypeOptions.map(rt => rt.id),
    [rangeTypeFilter, rangeTypeOptions],
  );

  const filteredShifts = useMemo(
    () => filterCalendarShifts(shifts, effectiveDutyTypeFilter, false),
    [shifts, effectiveDutyTypeFilter],
  );

  const filteredRanges = useMemo(
    () => ranges.filter(r => effectiveRangeTypeFilter.includes(r.range_type)),
    [ranges, effectiveRangeTypeFilter],
  );

  const shiftEvents = useMemo(
    () => filteredShifts.map((shift) => {
      const event = shiftToCalendarEvent(shift);
      return {
        ...event,
        classNames: [...CALENDAR_EVENT_INTERACTION_CLASSES, ...event.classNames],
      };
    }),
    [filteredShifts],
  );

  const rangeCalEvents = useMemo(() =>
    filteredRanges.map((r) => {
      const hasTime = !!r.start_time && !!r.end_time;
      return {
        id: `range-${r.id}`,
        title: `${RANGE_TYPE_LABELS[r.range_type] ?? r.range_type} — ${r.location}`,
        start: hasTime ? `${r.date}T${r.start_time}` : r.date,
        end: hasTime ? `${r.date}T${r.end_time}` : r.date,
        allDay: !hasTime,
        backgroundColor: RANGE_TYPE_COLORS[r.range_type] ?? "#7c3aed",
        borderColor: RANGE_TYPE_COLORS[r.range_type] ?? "#7c3aed",
        classNames: [...CALENDAR_EVENT_INTERACTION_CLASSES],
        extendedProps: { rangeId: r.id },
      };
    }),
  [filteredRanges]);

  const events = useMemo(() => [...shiftEvents, ...rangeCalEvents], [shiftEvents, rangeCalEvents]);

  function handleDateClick(_: { dateStr: string }) {
    setSelectedShift(null);
  }

  function handleEventClick(arg: EventClickArg) {
    const rangeId = arg.event.extendedProps.rangeId as string | undefined;
    if (rangeId) {
      setSelectedRangeId(rangeId);
      return;
    }
    const shiftId = arg.event.extendedProps.shiftId;
    const shift = shifts.find(s => s.id === shiftId);
    if (shift) setSelectedShift(shift);
  }

  const calendarMinWidthPx = calendarViewMinWidth(activeViewType);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 text-sm items-center">
            <CheckboxListDropdown
              items={dutyTypesInView.map((dt) => ({ id: dt.id, label: dt.name }))}
              selected={effectiveDutyTypeFilter}
              onChange={setDutyTypeFilter}
              triggerLabel={t("unit_calendar.duty_type_filter_label") || "סוגי תורנויות"}
              panelDir="rtl"
            />
          {rangesEnabled && (
            <CheckboxListDropdown
              items={rangeTypeOptions.map((rt) => ({ id: rt.id, label: rt.name }))}
              selected={effectiveRangeTypeFilter}
              onChange={setRangeTypeFilter}
              triggerLabel={t("unit_calendar.range_filter_label") || "סוגי מטווחים"}
              panelDir="rtl"
            />
          )}
      </div>

      {loading && <p className="text-gray-500 text-sm">{t("unit_calendar.loading")}</p>}
      {error && <p className="text-red-500 text-sm" data-testid="unit-calendar-error">{error}</p>}

      <div
        data-testid="fullcalendar"
        className="text-sm"
        style={{ "--fc-grid-min-width": calendarMinWidthPx ? `${calendarMinWidthPx}px` : undefined } as CSSProperties}
      >
        <FullCalendar
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          initialView="dayGridMonth"
          firstDay={0}
          eventDisplay="block"
          events={events}
          dateClick={handleDateClick}
          eventClick={handleEventClick}
          datesSet={handleDatesSet}
          locales={[heLocale]}
          locale="he"
          height="auto"
          headerToolbar={{ left: "prev,next today", center: "title", right: "timeGridThreeDay,timeGridWeek,dayGridMonth" }}
          buttonText={{
            today: t("unit_calendar.today") || "היום",
            month: t("unit_calendar.view_month") || "חודש",
            week: t("unit_calendar.view_week") || "שבוע",
            timeGridThreeDay: t("unit_calendar.view_3day") || "3 ימים",
          }}
          noEventsText={t("unit_calendar.none")}
          slotMinTime="00:00:00"
          slotMaxTime="24:00:00"
          slotLabelFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
          views={{
            dayGridMonth: { displayEventTime: false },
            timeGridWeek: { displayEventTime: true },
            timeGridThreeDay: { type: "timeGrid", duration: { days: 3 }, displayEventTime: true },
          }}
          eventContent={(arg) => {
            const rangeId = arg.event.extendedProps.rangeId as string | undefined;
            if (rangeId) {
              const range = ranges.find(r => r.id === rangeId);
              if (!range) return <div />;
              return (
                <div className="text-xs leading-tight px-1 overflow-hidden w-full">
                  <span className="font-semibold truncate">
                    {RANGE_TYPE_LABELS[range.range_type] ?? range.range_type} — {range.location}
                  </span>
                  <div className="truncate">
                    {range.primary_filled ?? 0}/{range.required_count} {t("unit_calendar.soldiers_count")}
                    {range.reserve_count > 0 && (
                      <span className="mr-1">| {range.reserve_filled ?? 0}/{range.reserve_count} {t("reserve_label")}</span>
                    )}
                  </div>
                </div>
              );
            }
            const shift = shifts.find(s => s.id === arg.event.extendedProps.shiftId);
            if (!shift) return <div />;
            const ineligibleAssignees = canSeeEligibilityBadges
              ? shift.assignees.filter((a) => a.weapon_ineligible || a.range_eligibility?.eligible === false)
              : [];
            const plannedCoverageAssignees = canSeeEligibilityBadges && ineligibleAssignees.length === 0
              ? shift.assignees.filter((a) => a.range_eligibility?.qualification_source === "planned_range" && a.range_eligibility.covered_by_range_date)
              : [];
            const plannedCoverageAssignee = plannedCoverageAssignees[0];
            const swapCount = (arg.event.extendedProps.swapCount as number) ?? 0;
            const isMultiDay = shiftSpansMultipleDays(shift);
            const edgeLabels = isMultiDay ? shiftEdgeLabels(shift) : null;
            return (
              <div className="text-xs leading-tight px-1 overflow-hidden w-full">
                {edgeLabels && (
                  <div dir="rtl" className="flex items-center justify-between gap-1 text-[10px] opacity-90 w-full">
                    <span className="flex-shrink-0">{edgeLabels.start}</span>
                    <span className="flex-shrink-0">{edgeLabels.end}</span>
                  </div>
                )}
                <div className="flex items-center gap-1 w-full">
                  <span className="font-semibold truncate flex-1">{shift.duty_type_name} — {shift.duty_location_name}</span>
                  {ineligibleAssignees.length > 0 && (
                    <span
                      data-testid={`shift-warning-badge-${shift.id}`}
                      aria-label={t("unit_calendar.eventWarningBadge", { count: ineligibleAssignees.length })}
                      title={
                        ineligibleAssignees.length === 1 && ineligibleAssignees[0].range_eligibility
                          ? formatRangeEligibilityExplanation(ineligibleAssignees[0].range_eligibility, t)
                          : t("unit_calendar.eventWarningBadge", { count: ineligibleAssignees.length })
                      }
                      className="inline-flex items-center gap-0.5 rounded bg-red-100 px-1 text-red-700 dark:bg-red-950 dark:text-red-300 flex-shrink-0"
                    >
                      ⚠<span className="text-[10px] leading-4">{ineligibleAssignees.length}</span>
                    </span>
                  )}
                  {plannedCoverageAssignee?.range_eligibility?.covered_by_range_date && (
                    <span
                      data-testid={`shift-info-badge-${shift.id}`}
                      aria-label={t("range_qualification.calendarBadge.info")}
                      title={
                        plannedCoverageAssignees.length === 1
                          ? t("unit_calendar.eventInfoBadge", {
                              rangeType:
                                RANGE_TYPE_LABELS[plannedCoverageAssignee.range_eligibility.covering_range_type ?? ""]
                                ?? plannedCoverageAssignee.range_eligibility.covering_range_type,
                              date: formatDate(plannedCoverageAssignee.range_eligibility.covered_by_range_date),
                            })
                          : t("unit_calendar.eventInfoBadgeCount", { count: plannedCoverageAssignees.length })
                      }
                      className="inline-flex items-center gap-0.5 rounded bg-blue-100 px-1 text-blue-700 dark:bg-blue-950 dark:text-blue-300 flex-shrink-0"
                    >
                      ℹ<span className="text-[10px] leading-4">{plannedCoverageAssignees.length}</span>
                    </span>
                  )}
                  {swapCount > 0 && (
                    <span className="inline-flex items-center gap-0.5 bg-orange-500 text-white rounded-full px-1 text-[10px] leading-4 flex-shrink-0 min-w-[1.25rem] text-center">
                      <ArrowLeftRight size={10} />
                      {swapCount}
                    </span>
                  )}
                </div>
                <div className="truncate">
                  {shift.assigned_count} {t("unit_calendar.soldiers_count")}
                  {shift.reserve_count > 0 && (
                    <span className="mr-1">| {shift.reserve_count} {t("reserve_label")}</span>
                  )}
                </div>
              </div>
            );
          }}
        />
      </div>

      {selectedShift && (
        <ShiftDetailPanel
          shift={selectedShift}
          onClose={() => setSelectedShift(null)}
          onRefreshNeeded={() => {
            const r = dateRangeRef.current;
            if (r) fetchData(r.from, r.to);
          }}
        />
      )}

      {selectedRangeId && (
        <RangeDetailModal rangeId={selectedRangeId} onClose={() => setSelectedRangeId(null)} />
      )}
    </div>
  );
}
