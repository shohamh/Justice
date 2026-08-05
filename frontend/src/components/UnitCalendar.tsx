import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import heLocale from "@fullcalendar/core/locales/he";
import type { EventClickArg, DatesSetArg } from "@fullcalendar/core";

import { CalendarShift, getCalendarShifts } from "../api/calendar";
import { loadCalendarData } from "../api/calendarData";
import { RangeEvent, getRanges } from "../api/ranges";
import { RANGE_TYPE_LABELS } from "../utils/rangeLabels";
import { usePublicSettings } from "../hooks/usePublicSettings";
import ShiftDetailPanel from "./ShiftDetailPanel";
import { calendarViewMinWidth } from "../utils/calendarViewWidth";
import CheckboxListDropdown from "./CheckboxListDropdown";

const RANGE_TYPE_COLORS: Record<string, string> = {
  laser: "#7c3aed",
  live: "#db2777",
  alal: "#0891b2",
};


interface UnitCalendarProps {
  nodeId: string;
}

export default function UnitCalendar({ nodeId }: UnitCalendarProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const publicSettings = usePublicSettings();
  const rangesEnabled = publicSettings?.["mitvachim.enabled"] === true;
  const [shifts, setShifts] = useState<CalendarShift[]>([]);
  const [ranges, setRanges] = useState<RangeEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedShift, setSelectedShift] = useState<CalendarShift | null>(null);
  const [dutyTypeFilter, setDutyTypeFilter] = useState<string[]>([]);
  const [rangeTypeFilter, setRangeTypeFilter] = useState<string[]>([]);
  const [activeViewType, setActiveViewType] = useState("dayGridMonth");

  const dateRangeRef = useRef<{ from: string; to: string } | null>(null);

  const fetchData = useCallback(async (from: string, to: string) => {
    if (!nodeId) return;
    setLoading(true);
    setError(null);
    try {
      const { calendar, ranges: rangeEvents } = await loadCalendarData(
        () => getCalendarShifts(nodeId, { date_from: from, date_to: to }),
        () => getRanges(nodeId, from, to),
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
  }, [nodeId, rangesEnabled, t]);

  useEffect(() => {
    dateRangeRef.current = null;
    setShifts([]);
    setRanges([]);
    setSelectedShift(null);
  }, [nodeId]);

  function handleDatesSet(arg: DatesSetArg) {
    setActiveViewType(arg.view.type);
    const from = arg.start.toISOString().slice(0, 10);
    const to = arg.end.toISOString().slice(0, 10);
    const prev = dateRangeRef.current;
    if (prev && prev.from === from && prev.to === to) return;
    dateRangeRef.current = { from, to };
    fetchData(from, to);
  }

  const filteredShifts = useMemo(() => {
    if (dutyTypeFilter.length === 0) return shifts;
    return shifts.filter(s => dutyTypeFilter.includes(s.duty_type_id));
  }, [shifts, dutyTypeFilter]);

  const filteredRanges = useMemo(() => {
    if (rangeTypeFilter.length === 0) return ranges;
    return ranges.filter(r => rangeTypeFilter.includes(r.range_type));
  }, [ranges, rangeTypeFilter]);

  const shiftEvents = useMemo(() => {
    const out: {
      id: string;
      title: string;
      start: string;
      end: string;
      allDay: boolean;
      backgroundColor: string;
      borderColor: string;
      classNames: string[];
      extendedProps: { shiftId: string; dutyTypeId: string; swapCount: number };
    }[] = [];
    for (const s of filteredShifts) {
      // start_at/end_at carry the shift's real wall-clock times, so the week
      // view can position events within hour slots. Shifts that just use the
      // full-day default (00:00-23:59) have no real hour data, so treat them
      // as all-day: otherwise the week view crams them into narrow near-24h
      // slivers instead of a compact banner.
      const isFullDayDefault = s.start_time === "00:00" && s.end_time === "23:59";
      out.push({
        id: s.id,
        title: `${s.duty_type_name} — ${s.duty_location_name}`,
        start: isFullDayDefault ? s.start_date : s.start_at,
        end: isFullDayDefault ? s.end_date : s.end_at,
        allDay: isFullDayDefault,
        backgroundColor: s.duty_type_color,
        borderColor: s.duty_type_color,
        classNames: s.reserve_count > 0 ? ["fc-event-has-reserves"] : [],
        extendedProps: { shiftId: s.id, dutyTypeId: s.duty_type_id, swapCount: s.swap_request_count ?? 0 },
      });
    }
    return out;
  }, [filteredShifts]);

  const rangeCalEvents = useMemo(() =>
    filteredRanges.map((r) => ({
      id: `range-${r.id}`,
      title: `${RANGE_TYPE_LABELS[r.range_type] ?? r.range_type} — ${r.location}`,
      start: r.date,
      allDay: true,
      backgroundColor: RANGE_TYPE_COLORS[r.range_type] ?? "#7c3aed",
      borderColor: RANGE_TYPE_COLORS[r.range_type] ?? "#7c3aed",
      classNames: [] as string[],
      extendedProps: { rangeId: r.id },
    })),
  [filteredRanges]);

  const events = useMemo(() => [...shiftEvents, ...rangeCalEvents], [shiftEvents, rangeCalEvents]);

  function handleDateClick(_: { dateStr: string }) {
    setSelectedShift(null);
  }

  function handleEventClick(arg: EventClickArg) {
    const rangeId = arg.event.extendedProps.rangeId as string | undefined;
    if (rangeId) {
      navigate(`/ranges?event=${rangeId}`);
      return;
    }
    const shiftId = arg.event.extendedProps.shiftId;
    const shift = shifts.find(s => s.id === shiftId);
    if (shift) setSelectedShift(shift);
  }

  const dutyTypesInView = useMemo(() => {
    const seen = new Map<string, string>();
    for (const s of shifts) {
      if (!seen.has(s.duty_type_id)) seen.set(s.duty_type_id, s.duty_type_name);
    }
    return Array.from(seen.entries()).map(([id, name]) => ({ id, name }));
  }, [shifts]);

  const rangeTypeOptions = useMemo(
    () => Object.entries(RANGE_TYPE_LABELS).map(([id, name]) => ({ id, name })),
    [],
  );

  const calendarMinWidthPx = calendarViewMinWidth(activeViewType);

  return (
    <div className="space-y-4">
      {(dutyTypesInView.length > 1 || rangesEnabled) && (
        <div className="flex flex-wrap gap-3 text-sm items-center">
          {dutyTypesInView.length > 1 && (
            <CheckboxListDropdown
              items={dutyTypesInView.map((dt) => ({ id: dt.id, label: dt.name }))}
              selected={dutyTypeFilter}
              onChange={setDutyTypeFilter}
              triggerLabel={t("unit_calendar.duty_type_filter_label") || "סוגי תורנויות"}
              panelDir="rtl"
            />
          )}
          {rangesEnabled && (
            <CheckboxListDropdown
              items={rangeTypeOptions.map((rt) => ({ id: rt.id, label: rt.name }))}
              selected={rangeTypeFilter}
              onChange={setRangeTypeFilter}
              triggerLabel={t("unit_calendar.range_filter_label") || "סוגי מטווחים"}
              panelDir="rtl"
            />
          )}
        </div>
      )}

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
                </div>
              );
            }
            const shift = shifts.find(s => s.id === arg.event.extendedProps.shiftId);
            if (!shift) return <div />;
            const swapCount = (arg.event.extendedProps.swapCount as number) ?? 0;
            return (
              <div className="text-xs leading-tight px-1 overflow-hidden w-full">
                <div className="flex items-center gap-1 w-full">
                  <span className="font-semibold truncate flex-1">{shift.duty_type_name} — {shift.duty_location_name}</span>
                  {swapCount > 0 && (
                    <span className="bg-orange-500 text-white rounded-full px-1 text-[10px] leading-4 flex-shrink-0 min-w-[1.25rem] text-center">
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
    </div>
  );
}
