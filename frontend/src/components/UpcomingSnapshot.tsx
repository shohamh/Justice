import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { UpcomingDay, UpcomingAssignment } from "../api/commanderDashboard";
import SoldierLink from "./SoldierLink";

interface Props {
  data: UpcomingDay[] | null;
}

function formatDate(dateStr: string) {
  const d = new Date(dateStr);
  const day = d.getDate().toString().padStart(2, "0");
  const month = (d.getMonth() + 1).toString().padStart(2, "0");
  const weekday = d.toLocaleDateString("he-IL", { weekday: "short" });
  return { weekday, dayMonth: `${day}.${month}` };
}

function Badge({ a, onSelect }: { a: UpcomingAssignment; onSelect: (a: UpcomingAssignment) => void }) {
  return (
    <button
      onClick={() => onSelect(a)}
      className={`text-xs rounded px-2 py-0.5 cursor-pointer border ${
        a.is_reserve ? "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800" : "bg-gray-100 dark:bg-gray-700 border-gray-200 dark:border-gray-600"
      }`}
    >
      {a.soldier_name || a.duty_type_id?.slice(0, 6) || "?"}
    </button>
  );
}

export default function UpcomingSnapshot({ data }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<UpcomingAssignment | null>(null);

  function handleForcedRelease(a: UpcomingAssignment) {
    const confirmed = window.confirm(
      `פעולה זו תפעיל מנגנון הקפצה פיקודית עבור ${a.soldier_name || "החייל"} — מיועד למקרים קיצוניים בלבד (מחלה, צורך מבצעי דחוף). להמשיך?`
    );
    if (!confirmed) return;
    navigate(`/commander/hakpaza?soldierId=${a.soldier_id}&assignmentId=${a.assignment_id}`);
  }
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_upcoming")}</p>;
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="space-y-2" data-testid="upcoming-snapshot">
      {data.map((day) => {
        const isToday = day.date === today;
        const { weekday, dayMonth } = formatDate(day.date);
        return (
          <div key={day.date} className={`flex items-center gap-3 p-2 rounded ${isToday ? "bg-indigo-50 dark:bg-indigo-950" : ""}`}>
            <span className="text-sm font-medium w-20 text-left" dir="ltr">{weekday} {dayMonth}</span>
            <div className="flex-1 flex flex-wrap gap-1">
              {day.assignments.length === 0 ? (
                <span className="text-xs text-gray-400">{t("command_dashboard.none")}</span>
              ) : (
                day.assignments.map((a) => <Badge key={a.assignment_id} a={a} onSelect={setSelected} />)
              )}
            </div>
            <span className="text-xs text-gray-500 dark:text-gray-400">{day.assignments.length}</span>
          </div>
        );
      })}

      {selected && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setSelected(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-5 w-72" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-3">
              <div className="font-bold text-lg">
                {selected.soldier_id ? (
                  <SoldierLink id={selected.soldier_id} name={selected.soldier_name || "?"} />
                ) : (
                  selected.soldier_name || "?"
                )}
              </div>
              <button onClick={() => setSelected(null)} aria-label="סגור" className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
            </div>
            <div className="space-y-1 text-sm">
              <div><span className="text-gray-500 dark:text-gray-400">תורנות:</span> {selected.duty_type_name || selected.duty_type_id?.slice(0, 6) || "?"}</div>
              <div><span className="text-gray-500 dark:text-gray-400">יחידה:</span> {selected.node_name || "?"}</div>
              {selected.is_reserve && <div className="text-amber-700 dark:text-amber-400 font-medium">רזרבה</div>}
            </div>
            {selected.soldier_id && (
              <button
                onClick={() => handleForcedRelease(selected)}
                className="mt-4 w-full px-3 py-1.5 rounded text-sm font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-800"
              >
                שחרור פיקודי
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
