import { useEffect, useMemo, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
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
      // d.end_date is already exclusive (the day after the last day), matching
      // FullCalendar's own exclusive `end` convention -- no +1 day needed here.
      const color = dutyTypeColor(d.duty_type_id);
      return {
        id: d.assignment_id,
        title: typeNames[d.duty_type_id] ?? "תורנות",
        start: d.start_date,
        end: d.end_date,
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
        plugins={[dayGridPlugin]}
        initialView="dayGridMonth"
        locale={heLocale}
        events={[...dutyEvents, ...holidayEvents]}
        headerToolbar={{ start: "prev,next", center: "title", end: "" }}
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
