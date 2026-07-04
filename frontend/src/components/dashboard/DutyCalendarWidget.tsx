import { useEffect, useMemo, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import heLocale from "@fullcalendar/core/locales/he";
import { EffectiveDuty } from "../../api/assignments";
import { Holiday, listHolidays } from "../../api/calendarHolidays";
import { dutyTypeColor } from "../../utils/dutyTypeColor";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  onOpenDuty: (duty: EffectiveDuty) => void;
}

export default function DutyCalendarWidget({ duties, typeNames, onOpenDuty }: Props) {
  const [holidays, setHolidays] = useState<Holiday[]>([]);

  useEffect(() => {
    const year = new Date().getFullYear();
    void Promise.all([
      listHolidays(year),
      listHolidays(year + 1),
    ])
      .then(([current, next]) => setHolidays([...current, ...next]))
      .catch(() => {});
  }, []);

  const dutyEvents = useMemo(() =>
    duties.map((d) => {
      // start_at/end_at carry the duty's real wall-clock times so the week
      // view can position it within hour slots. Duties that just use the
      // full-day default (00:00-23:59) have no real hour data, so treat them
      // as all-day: otherwise the week view crams them into narrow near-24h
      // slivers instead of a compact banner.
      const isFullDayDefault = d.start_time === "00:00" && d.end_time === "23:59";
      const color = dutyTypeColor(d.duty_type_id);
      return {
        id: d.assignment_id,
        title: typeNames[d.duty_type_id] ?? "תורנות",
        start: isFullDayDefault ? d.start_date : d.start_at,
        end: isFullDayDefault ? d.end_date : d.end_at,
        allDay: isFullDayDefault,
        backgroundColor: color,
        borderColor: color,
        extendedProps: { duty: d },
      };
    }),
  [duties, typeNames]);

  const holidayEvents = useMemo(() =>
    holidays.map((h) => ({
      id: `holiday-${h.date}`,
      title: h.name,
      start: h.date,
      display: "background",
      backgroundColor: "#fef9c3",
      extendedProps: { isHoliday: true },
    })),
  [holidays]);

  function handleEventMouseEnter(info: { event: { extendedProps: { isHoliday?: boolean } }; el: HTMLElement }) {
    if (info.event.extendedProps.isHoliday) return;
    info.el.style.filter = "brightness(0.85)";
  }

  function handleEventMouseLeave(info: { event: { extendedProps: { isHoliday?: boolean } }; el: HTMLElement }) {
    info.el.style.filter = "";
  }

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">היומן שלי</h2>
      <FullCalendar
        plugins={[dayGridPlugin, timeGridPlugin]}
        initialView="dayGridMonth"
        firstDay={0}
        locale={heLocale}
        events={[...dutyEvents, ...holidayEvents]}
        headerToolbar={{ start: "prev,next", center: "title", end: "dayGridMonth,timeGridWeek" }}
        slotMinTime="00:00:00"
        slotMaxTime="24:00:00"
        views={{
          dayGridMonth: { displayEventTime: false },
          timeGridWeek: { displayEventTime: true },
        }}
        height="auto"
        editable={false}
        selectable={false}
        eventClick={(info) => {
          if (info.event.extendedProps.isHoliday) return;
          const duty = info.event.extendedProps.duty as EffectiveDuty;
          onOpenDuty(duty);
        }}
        eventMouseEnter={handleEventMouseEnter}
        eventMouseLeave={handleEventMouseLeave}
      />
    </section>
  );
}
