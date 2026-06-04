import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import heLocale from "@fullcalendar/core/locales/he";
import type { EventClickArg, DatesSetArg } from "@fullcalendar/core";

import { CalendarShift, getCalendarShifts } from "../api/calendar";
import ShiftDetailPanel from "./ShiftDetailPanel";


interface UnitCalendarProps {
  nodeId: string;
}

export default function UnitCalendar({ nodeId }: UnitCalendarProps) {
  const { t } = useTranslation();
  const [shifts, setShifts] = useState<CalendarShift[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedShift, setSelectedShift] = useState<CalendarShift | null>(null);
  const [dutyTypeFilter, setDutyTypeFilter] = useState<string | null>(null);

  const dateRangeRef = useRef<{ from: string; to: string } | null>(null);

  const fetchData = useCallback(async (from: string, to: string) => {
    if (!nodeId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getCalendarShifts(nodeId, { date_from: from, date_to: to });
      setShifts(data.shifts);
      setSelectedShift(prev => {
        if (!prev) return null;
        return data.shifts.find(s => s.id === prev.id) ?? prev;
      });
    } catch {
      setError(t("unit_calendar.error") || "Failed to load calendar");
    } finally {
      setLoading(false);
    }
  }, [nodeId, t]);

  useEffect(() => {
    dateRangeRef.current = null;
    setShifts([]);
    setSelectedShift(null);
  }, [nodeId]);

  function handleDatesSet(arg: DatesSetArg) {
    const from = arg.start.toISOString().slice(0, 10);
    const to = arg.end.toISOString().slice(0, 10);
    const prev = dateRangeRef.current;
    if (prev && prev.from === from && prev.to === to) return;
    dateRangeRef.current = { from, to };
    fetchData(from, to);
  }

  const filteredShifts = useMemo(() => {
    if (!dutyTypeFilter) return shifts;
    return shifts.filter(s => s.duty_type_id === dutyTypeFilter);
  }, [shifts, dutyTypeFilter]);

  const events = useMemo(() => {
    const out: {
      id: string;
      title: string;
      start: string;
      end: string;
      backgroundColor: string;
      borderColor: string;
      classNames: string[];
      extendedProps: { shiftId: string; dutyTypeId: string };
    }[] = [];
    for (const s of filteredShifts) {
      const endDate = new Date(s.end_date);
      endDate.setDate(endDate.getDate() + 1);
      out.push({
        id: s.id,
        title: `${s.duty_type_name} — ${s.duty_location_name}`,
        start: s.start_date,
        end: endDate.toISOString().slice(0, 10),
        backgroundColor: s.duty_type_color,
        borderColor: s.duty_type_color,
        classNames: s.reserve_count > 0 ? ["fc-event-has-reserves"] : [],
        extendedProps: { shiftId: s.id, dutyTypeId: s.duty_type_id },
      });
    }
    return out;
  }, [filteredShifts]);

  function handleDateClick(_arg: { dateStr: string }) {
    setSelectedShift(null);
  }

  function handleEventClick(arg: EventClickArg) {
    const shiftId = arg.event.extendedProps.shiftId;
    const shift = shifts.find(s => s.id === shiftId);
    if (shift) setSelectedShift(shift);
  }

  function toggleFilter(dtId: string) {
    setDutyTypeFilter((prev) => (prev === dtId ? null : dtId));
  }

  const dutyTypesInView = useMemo(() => {
    const seen = new Map<string, string>();
    for (const s of shifts) {
      if (!seen.has(s.duty_type_id)) seen.set(s.duty_type_id, s.duty_type_name);
    }
    return Array.from(seen.entries()).map(([id, name]) => ({ id, name }));
  }, [shifts]);

  return (
    <div className="space-y-4">
      {dutyTypesInView.length > 1 && (
        <div className="flex flex-wrap gap-2 text-sm">
          <span className="text-gray-500">{t("unit_calendar.filter_label") || "סינון:"}</span>
          {dutyTypesInView.map((dt) => (
            <button
              key={dt.id}
              onClick={() => toggleFilter(dt.id)}
              data-testid={`filter-chip-${dt.id}`}
              className={`px-2 py-1 rounded-full border text-xs ${
                dutyTypeFilter === dt.id ? "bg-indigo-100 border-indigo-400 text-indigo-700" : "bg-white border-gray-300 text-gray-600"
              }`}
            >
              {dt.name}
            </button>
          ))}
        </div>
      )}

      {loading && <p className="text-gray-500 text-sm">{t("unit_calendar.loading")}</p>}
      {error && <p className="text-red-500 text-sm" data-testid="unit-calendar-error">{error}</p>}

      <div data-testid="fullcalendar" className="text-sm">
        <FullCalendar
          plugins={[dayGridPlugin, interactionPlugin]}
          initialView="dayGridMonth"
          events={events}
          dateClick={handleDateClick}
          eventClick={handleEventClick}
          datesSet={handleDatesSet}
          locales={[heLocale]}
          locale="he"
          height="auto"
          headerToolbar={{ left: "prev,next today", center: "title", right: "dayGridMonth" }}
          buttonText={{ today: t("unit_calendar.today") || "היום" }}
          noEventsText={t("unit_calendar.none")}
          displayEventTime={false}
          eventContent={(arg) => {
            const shift = shifts.find(s => s.id === arg.event.extendedProps.shiftId);
            if (!shift) return <div />;
            return (
              <div className="text-xs leading-tight px-1 overflow-hidden w-full">
                <div className="font-semibold truncate">{shift.duty_type_name} — {shift.duty_location_name}</div>
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
