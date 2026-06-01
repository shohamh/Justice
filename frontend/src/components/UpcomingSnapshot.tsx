import { useTranslation } from "react-i18next";
import type { UpcomingDay } from "../api/commanderDashboard";

interface Props {
  data: UpcomingDay[] | null;
}

export default function UpcomingSnapshot({ data }: Props) {
  const { t } = useTranslation();
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_upcoming")}</p>;
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="space-y-2" data-testid="upcoming-snapshot">
      {data.map((day) => {
        const isToday = day.date === today;
        return (
          <div key={day.date} className={`flex items-center gap-3 p-2 rounded ${isToday ? "bg-indigo-50" : ""}`}>
            <span className="text-sm font-medium w-16">{new Date(day.date).toLocaleDateString("he-IL", { weekday: "short", day: "numeric" })}</span>
            <div className="flex-1 flex gap-1">
              {day.assignments.length === 0 ? (
                <span className="text-xs text-gray-400">{t("command_dashboard.none")}</span>
              ) : (
                day.assignments.map((a) => (
                  <span key={a.assignment_id} className="text-xs bg-gray-100 rounded px-2 py-0.5">{a.duty_type_id.slice(0, 6)}</span>
                ))
              )}
            </div>
            <span className="text-xs text-gray-500">{day.assignments.length}</span>
          </div>
        );
      })}
    </div>
  );
}
