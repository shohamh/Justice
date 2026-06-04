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
  const today = new Date().toISOString().split("T")[0];
  const past = duties
    .filter((d) => d.end_date < today)
    .sort((a, b) => b.start_date.localeCompare(a.start_date));

  const avgActiveDays = Math.round(avg(allRows, "active_days"));
  const avgScore = avg(allRows, "cumulative_score").toFixed(2);
  const avgNorm = avg(allRows, "normalised_score").toFixed(3);

  return (
    <section className="bg-white rounded-lg shadow p-4 space-y-4" dir="rtl">
      <h2 className="text-lg font-semibold">היסטוריית תורנויות</h2>

      {/* Scoring metrics */}
      <div className="grid grid-cols-3 gap-3 text-sm">
        {[
          { label: "ניקוד מצטבר", my: Number(myRow?.cumulative_score ?? 0).toFixed(2), unit: avgScore },
          { label: "ימים פעילים", my: myRow?.active_days ?? 0, unit: avgActiveDays },
          { label: "ניקוד מנורמל", my: Number(myRow?.normalised_score ?? 0).toFixed(3), unit: avgNorm },
        ].map(({ label, my, unit }) => (
          <div key={label} className="bg-gray-50 rounded-lg p-3 text-center">
            <div className="text-xs text-gray-500 mb-1">{label}</div>
            <div className="text-lg font-semibold text-indigo-700">{my}</div>
            <div className="text-xs text-gray-400 mt-1">ממוצע יחידה: {unit}</div>
          </div>
        ))}
      </div>

      {/* Past duties list */}
      {past.length === 0 ? (
        <p className="text-sm text-gray-500">אין היסטוריית תורנויות</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 border-b">
              <th className="text-right pb-2 font-medium">תאריך</th>
              <th className="text-right pb-2 font-medium">סוג</th>
              <th className="text-right pb-2 font-medium">מיקום</th>
            </tr>
          </thead>
          <tbody>
            {past.map((d) => (
              <tr key={d.assignment_id} className="border-b last:border-0">
                <td className="py-2">{formatDateRange(d.start_date, d.end_date)}</td>
                <td className="py-2">{typeNames[d.duty_type_id] ?? "—"}</td>
                <td className="py-2">{locationNames[d.duty_location_id] ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
