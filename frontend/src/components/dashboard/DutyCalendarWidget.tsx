import { useMemo } from "react";
import { Link } from "react-router-dom";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import heLocale from "@fullcalendar/core/locales/he";
import { EffectiveDuty } from "../../api/assignments";
import { dutyTypeColor } from "../../utils/dutyTypeColor";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
}

export default function DutyCalendarWidget({ duties, typeNames }: Props) {
  const events = useMemo(() =>
    duties.map((d) => {
      const endDate = new Date(d.end_date);
      endDate.setDate(endDate.getDate() + 1);
      const color = dutyTypeColor(d.duty_type_id);
      return {
        id: d.assignment_id,
        title: typeNames[d.duty_type_id] ?? "תורנות",
        start: d.start_date,
        end: endDate.toISOString().split("T")[0],
        backgroundColor: color,
        borderColor: color,
      };
    }),
  [duties, typeNames]);

  return (
    <section className="bg-white rounded-lg shadow p-4" dir="rtl">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">היומן שלי</h2>
        <Link to="/my-duties" className="text-sm text-indigo-600 hover:text-indigo-800">
          לכל היומן שלי →
        </Link>
      </div>
      <FullCalendar
        plugins={[dayGridPlugin]}
        initialView="dayGridMonth"
        locale={heLocale}
        events={events}
        headerToolbar={{ start: "prev,next", center: "title", end: "" }}
        height="auto"
        editable={false}
        selectable={false}
        eventClick={() => {}}
      />
    </section>
  );
}
