import { RangeEvent } from "../../api/ranges";
import { RANGE_TYPE_LABELS } from "../../utils/rangeLabels";

interface Props {
  ranges: RangeEvent[];
  onOpenRange: (range: RangeEvent) => void;
}

export default function UpcomingRangesWidget({ ranges, onOpenRange }: Props) {
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = ranges
    .filter((r) => r.date > today && r.status === "planned")
    .sort((a, b) => a.date.localeCompare(b.date));

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">מטווחים קרובים</h2>
      {upcoming.length === 0 ? (
        <p className="text-sm text-gray-500">אין מטווחים קרובים</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-gray-600">
              <th className="text-right pb-2 font-medium">תאריך</th>
              <th className="text-right pb-2 font-medium">סוג</th>
              <th className="text-right pb-2 font-medium">מיקום</th>
              <th className="pb-2 w-6"></th>
            </tr>
          </thead>
          <tbody>
            {upcoming.map((range) => (
              <tr
                key={range.id}
                className="border-b last:border-0 dark:border-gray-600 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700"
                onClick={() => onOpenRange(range)}
                title="פתח פרטים"
              >
                <td className="py-2" dir="ltr">{range.date}</td>
                <td className="py-2">{RANGE_TYPE_LABELS[range.range_type] ?? range.range_type}</td>
                <td className="py-2">{range.location}</td>
                <td className="py-2 text-gray-400 text-xs">›</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
