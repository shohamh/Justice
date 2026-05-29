import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import heLocale from "@fullcalendar/core/locales/he";
import type { EventClickArg, DatesSetArg } from "@fullcalendar/core";

import { CalRow, CalAssignment, getUnitCalendar } from "../api/calendar";

interface UnitCalendarProps {
  nodeId: string;
}

export default function UnitCalendar({ nodeId }: UnitCalendarProps) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<CalRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<{
    assignment: CalAssignment;
    soldier_name: string;
  } | null>(null);
  const [dutyTypeFilter, setDutyTypeFilter] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<{ from: string; to: string } | null>(null);

  const fetchData = useCallback(async (from: string, to: string) => {
    if (!nodeId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getUnitCalendar(nodeId, { date_from: from, date_to: to });
      setRows(data);
    } catch {
      setError(t("unit_calendar.error") || "Failed to load calendar");
    } finally {
      setLoading(false);
    }
  }, [nodeId, t]);

  useEffect(() => {
    if (dateRange) fetchData(dateRange.from, dateRange.to);
  }, [dateRange, fetchData]);

  function handleDatesSet(arg: DatesSetArg) {
    const from = arg.start.toISOString().slice(0, 10);
    const to = arg.end.toISOString().slice(0, 10);
    setDateRange({ from, to });
  }

  const events = useMemo(() => {
    const out: {
      id: string;
      title: string;
      start: string;
      end: string;
      backgroundColor: string;
      borderColor: string;
      extendedProps: { soldier_name: string; duty_type_id: string; duty_location_name: string; soldier_id: string; assignment_id: string };
    }[] = [];
    for (const r of rows) {
      for (const a of r.assignments) {
        const endDate = new Date(a.end_date);
        endDate.setDate(endDate.getDate() + 1);
        out.push({
          id: `${a.assignment_id}-${a.start_date}`,
          title: a.duty_type_name,
          start: a.start_date,
          end: endDate.toISOString().slice(0, 10),
          backgroundColor: a.duty_type_color,
          borderColor: a.duty_type_color,
          extendedProps: {
            soldier_name: r.full_name,
            duty_type_id: a.duty_type_id,
            duty_location_name: a.duty_location_name,
            soldier_id: r.soldier_id,
            assignment_id: a.assignment_id,
          },
        });
      }
    }
    return out;
  }, [rows]);

  function handleDateClick(arg: { dateStr: string }) {
    setSelectedDate(arg.dateStr);
    setSelectedEvent(null);
  }

  function handleEventClick(arg: EventClickArg) {
    const props = arg.event.extendedProps;
    const endStr = arg.event.endStr || arg.event.startStr;
    const endDate = new Date(endStr);
    endDate.setDate(endDate.getDate() - 1);
    setSelectedEvent({
      soldier_name: props.soldier_name,
      assignment: {
        assignment_id: props.assignment_id,
        duty_type_id: props.duty_type_id,
        duty_type_name: arg.event.title,
        duty_type_color: arg.event.backgroundColor,
        duty_location_id: "",
        duty_location_name: props.duty_location_name,
        start_date: arg.event.startStr.slice(0, 10),
        end_date: endDate.toISOString().slice(0, 10),
      },
    });
    setSelectedDate(null);
  }

  const detailRows = useMemo(() => {
    const date = selectedDate;
    if (!date) return null;
    const out: { soldier_name: string; duty_type_name: string; duty_location_name: string }[] = [];
    for (const r of rows) {
      for (const a of r.assignments) {
        if (a.start_date <= date && a.end_date >= date) {
          if (dutyTypeFilter && a.duty_type_id !== dutyTypeFilter) continue;
          out.push({ soldier_name: r.full_name, duty_type_name: a.duty_type_name, duty_location_name: a.duty_location_name });
        }
      }
    }
    out.sort((a, b) => a.soldier_name.localeCompare(b.soldier_name));
    return out;
  }, [rows, selectedDate, dutyTypeFilter]);

  function toggleFilter(dtId: string) {
    setDutyTypeFilter((prev) => (prev === dtId ? null : dtId));
  }

  const dutyTypesInView = useMemo(() => {
    const seen = new Map<string, string>();
    for (const r of rows) {
      for (const a of r.assignments) {
        if (!seen.has(a.duty_type_id)) seen.set(a.duty_type_id, a.duty_type_name);
      }
    }
    return Array.from(seen.entries()).map(([id, name]) => ({ id, name }));
  }, [rows]);

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
        />
      </div>

      <div data-testid="calendar-detail" className="bg-white rounded-lg border p-4">
        {selectedEvent ? (
          <div>
            <h3 className="font-semibold mb-2">{t("unit_calendar.duty_detail") || "פרטי תורנות"}</h3>
            <table className="w-full text-sm text-right">
              <tbody>
                <tr className="border-b"><td className="p-1 font-medium">{t("unit_calendar.soldier")}</td><td className="p-1">{selectedEvent.soldier_name}</td></tr>
                <tr className="border-b"><td className="p-1 font-medium">{t("unit_calendar.duty_type") || "סוג תורנות"}</td><td className="p-1">{selectedEvent.assignment.duty_type_name}</td></tr>
                <tr className="border-b"><td className="p-1 font-medium">{t("unit_calendar.location") || "מיקום"}</td><td className="p-1">{selectedEvent.assignment.duty_location_name}</td></tr>
                <tr className="border-b"><td className="p-1 font-medium">{t("unit_calendar.from") || "מתאריך"}</td><td className="p-1">{selectedEvent.assignment.start_date}</td></tr>
                <tr><td className="p-1 font-medium">{t("unit_calendar.to") || "עד תאריך"}</td><td className="p-1">{selectedEvent.assignment.end_date}</td></tr>
              </tbody>
            </table>
          </div>
        ) : detailRows ? (
          <div>
            <h3 className="font-semibold mb-2">
              {t("unit_calendar.detail_table") || "תורנויות לתאריך"}
              {selectedDate && ` — ${selectedDate}`}
              {dutyTypeFilter && ` (${dutyTypesInView.find((d) => d.id === dutyTypeFilter)?.name})`}
            </h3>
            {detailRows.length === 0 ? (
              <p className="text-gray-500 text-sm">{t("unit_calendar.none")}</p>
            ) : (
              <table className="w-full text-sm text-right" data-testid="detail-table">
                <thead>
                  <tr className="border-b">
                    <th className="p-1">{t("unit_calendar.soldier")}</th>
                    <th className="p-1">{t("unit_calendar.duty_type") || "סוג תורנות"}</th>
                    <th className="p-1">{t("unit_calendar.location") || "מיקום"}</th>
                  </tr>
                </thead>
                <tbody>
                  {detailRows.map((r, i) => (
                    <tr key={i} className="border-b last:border-0" data-testid={`detail-row-${i}`}>
                      <td className="p-1">{r.soldier_name}</td>
                      <td className="p-1">{r.duty_type_name}</td>
                      <td className="p-1">{r.duty_location_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ) : (
          <p className="text-gray-400 text-sm">{t("unit_calendar.click_hint")}</p>
        )}
      </div>
    </div>
  );
}
