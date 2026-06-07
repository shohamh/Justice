import { Link } from "react-router-dom";
import { SwapRequest } from "../../api/swaps";
import { formatDateRange } from "../../utils/formatDate";

interface Props {
  swaps: SwapRequest[];
}

const STATUS_CHIPS: Record<string, string> = {
  open: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  pending_approval: "bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300",
  applied: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
  rejected: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
};

const STATUS_LABELS: Record<string, string> = {
  open: "פתוח",
  pending_approval: "ממתין לאישור",
  applied: "אושר",
  rejected: "נדחה",
};

export default function SwapStatusWidget({ swaps }: Props) {
  const active = swaps.filter((s) => s.status === "open" || s.status === "pending_approval");
  if (active.length === 0) return null;

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">ההחלפות שלי</h2>
        <Link to="/swaps" className="text-sm text-indigo-600 hover:text-indigo-800">
          לדף החלפות →
        </Link>
      </div>
      <ul className="space-y-2">
        {active.map((s) => (
          <li key={s.id} className="flex items-start justify-between text-sm border-b dark:border-gray-600 last:border-0 pb-2 last:pb-0 gap-2">
            <div className="space-y-0.5">
              <div className="font-medium">
                {s.duty_type_name ?? "תורנות"}
              </div>
              <div className="text-gray-500 text-xs">
                {s.duty_start_date && s.duty_end_date
                  ? formatDateRange(s.duty_start_date, s.duty_end_date)
                  : formatDateRange(s.duty_date, s.duty_date)}
              </div>
              {s.reason && <div className="text-gray-400 text-xs">{s.reason}</div>}
            </div>
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium shrink-0 ${STATUS_CHIPS[s.status] ?? "bg-gray-100 text-gray-600"}`}>
              {STATUS_LABELS[s.status] ?? s.status}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
