import { useState } from "react";
import { EffectiveDuty } from "../../api/assignments";
import { formatDateRange } from "../../utils/formatDate";
import ExplanationModal from "../ExplanationModal";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
}

export default function UpcomingDutiesWidget({ duties, typeNames, locationNames }: Props) {
  const [explanationId, setExplanationId] = useState<string | null>(null);
  const today = new Date().toISOString().split("T")[0];
  const upcoming = duties
    .filter((d) => d.end_date >= today)
    .sort((a, b) => a.start_date.localeCompare(b.start_date));

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">תורנויות קרובות</h2>
      {upcoming.length === 0 ? (
        <p className="text-sm text-gray-500">אין תורנויות קרובות</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-gray-600">
              <th className="text-right pb-2 font-medium">תאריך</th>
              <th className="text-right pb-2 font-medium">סוג</th>
              <th className="text-right pb-2 font-medium">מיקום</th>
              <th className="pb-2 w-8" />
            </tr>
          </thead>
          <tbody>
            {upcoming.map((d) => (
              <tr key={d.assignment_id} className="border-b dark:border-gray-600 last:border-0">
                <td className="py-2">{formatDateRange(d.start_date, d.end_date)}</td>
                <td className="py-2">{typeNames[d.duty_type_id] ?? "—"}</td>
                <td className="py-2">{locationNames[d.duty_location_id] ?? "—"}</td>
                <td className="py-2 w-8 text-center">
                  <button
                    className="text-gray-400 hover:text-indigo-600 text-xs font-bold border border-gray-300 dark:border-gray-600 rounded-full w-5 h-5 inline-flex items-center justify-center"
                    onClick={(e) => { e.stopPropagation(); setExplanationId(d.assignment_id); }}
                    title="למה קיבלתי תורנות זו?"
                  >
                    ?
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {explanationId && (
        <ExplanationModal
          assignmentId={explanationId}
          onClose={() => setExplanationId(null)}
        />
      )}
    </section>
  );
}
