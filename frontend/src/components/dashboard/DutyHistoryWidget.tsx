import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { EffectiveDuty } from "../../api/assignments";
import { TransparencyRow } from "../../api/scoring";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
  myRow: TransparencyRow | null;
  allRows: TransparencyRow[];
}

function formatDateRange(start: string, end: string): string {
  if (start === end) return new Date(start).toLocaleDateString("he-IL");
  return `${new Date(start).toLocaleDateString("he-IL")} – ${new Date(end).toLocaleDateString("he-IL")}`;
}

function avg(rows: TransparencyRow[], key: keyof TransparencyRow): number {
  if (rows.length === 0) return 0;
  return rows.reduce((s, r) => s + Number(r[key]), 0) / rows.length;
}

export default function DutyHistoryWidget({ duties, typeNames, locationNames, myRow, allRows }: Props) {
  const { t } = useTranslation();
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const today = new Date().toISOString().split("T")[0];
  const past = duties
    .filter((d) => d.end_date < today)
    .sort((a, b) => b.start_date.localeCompare(a.start_date));

  const avgActiveDays = Math.round(avg(allRows, "active_days"));
  const avgScore = avg(allRows, "cumulative_score").toFixed(2);
  const avgNorm = avg(allRows, "normalised_score").toFixed(3);

  const normTooltip = useMemo(() => {
    const avgCumFmt = avg(allRows, "cumulative_score").toFixed(3);
    return t("transparency.normalised_tooltip", { avgCumulative: avgCumFmt, avgActiveDays });
  }, [t, allRows, avgActiveDays]);

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-4" dir="rtl">
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-semibold">היסטוריית תורנויות</h2>
        <Link to="/transparency" className="text-sm text-indigo-600 hover:text-indigo-800">
          לדף השקיפות →
        </Link>
      </div>

      {/* Scoring metrics */}
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500 mb-1">ניקוד מצטבר</div>
          <div className="text-lg font-semibold text-indigo-700 dark:text-indigo-300">{Number(myRow?.cumulative_score ?? 0).toFixed(2)}</div>
          <div className="text-xs text-gray-400 mt-1">ממוצע יחידה: {avgScore}</div>
        </div>
        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500 mb-1">ימים פעילים</div>
          <div className="text-lg font-semibold text-indigo-700 dark:text-indigo-300">{myRow?.active_days ?? 0}</div>
          <div className="text-xs text-gray-400 mt-1">ממוצע יחידה: {avgActiveDays}</div>
        </div>
        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500 mb-1 inline-flex items-center gap-1">
            ניקוד מנורמל
            <button
              type="button"
              onClick={() => setTooltipOpen(true)}
              className="text-gray-400 hover:text-gray-600 text-xs border border-gray-300 rounded-full w-3.5 h-3.5 inline-flex items-center justify-center"
              aria-label="הסבר ניקוד מנורמל"
            >
              ?
            </button>
          </div>
          <div className="text-lg font-semibold text-indigo-700 dark:text-indigo-300">{Number(myRow?.normalised_score ?? 0).toFixed(3)}</div>
          <div className="text-xs text-gray-400 mt-1">ממוצע יחידה: {avgNorm}</div>
        </div>
      </div>

      {/* Past duties list */}
      {past.length === 0 ? (
        <p className="text-sm text-gray-500">אין היסטוריית תורנויות</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-gray-600">
              <th className="text-right pb-2 font-medium">תאריך</th>
              <th className="text-right pb-2 font-medium">סוג</th>
              <th className="text-right pb-2 font-medium">מיקום</th>
            </tr>
          </thead>
          <tbody>
            {past.map((d) => (
              <tr key={d.assignment_id} className="border-b dark:border-gray-600 last:border-0">
                <td className="py-2">{formatDateRange(d.start_date, d.end_date)}</td>
                <td className="py-2">{typeNames[d.duty_type_id] ?? "—"}</td>
                <td className="py-2">{locationNames[d.duty_location_id] ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Tooltip modal */}
      {tooltipOpen && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setTooltipOpen(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md mx-4" dir="rtl" onClick={(e) => e.stopPropagation()}>
            <p className="text-sm whitespace-pre-line">{normTooltip}</p>
            <div className="mt-4 text-left">
              <button type="button" className="bg-indigo-600 text-white px-3 py-1 rounded text-sm" onClick={() => setTooltipOpen(false)}>סגור</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
