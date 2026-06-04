import { Link } from "react-router-dom";
import { EffectiveDuty } from "../../api/assignments";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
}

function formatDateRange(start: string, end: string): string {
  if (start === end) return new Date(start).toLocaleDateString("he-IL");
  return `${new Date(start).toLocaleDateString("he-IL")} – ${new Date(end).toLocaleDateString("he-IL")}`;
}

export default function UpcomingDutiesWidget({ duties, typeNames, locationNames }: Props) {
  const today = new Date().toISOString().split("T")[0];
  const upcoming = duties
    .filter((d) => d.end_date >= today)
    .sort((a, b) => a.start_date.localeCompare(b.start_date))
    .slice(0, 5);

  return (
    <section className="bg-white rounded-lg shadow p-4" dir="rtl">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">תורנויות קרובות</h2>
        <Link to="/my-duties" className="text-sm text-indigo-600 hover:text-indigo-800">
          לכל התורנויות שלי →
        </Link>
      </div>
      {upcoming.length === 0 ? (
        <p className="text-sm text-gray-500">אין תורנויות קרובות</p>
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
            {upcoming.map((d) => (
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
