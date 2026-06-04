import { Link } from "react-router-dom";
import { SwapRequest } from "../../api/swaps";

interface Props {
  swaps: SwapRequest[];
}

const STATUS_CHIPS: Record<string, string> = {
  open: "bg-amber-100 text-amber-700",
  pending_approval: "bg-blue-100 text-blue-700",
};

const STATUS_LABELS: Record<string, string> = {
  open: "פתוח",
  pending_approval: "ממתין לאישור",
};

export default function SwapStatusWidget({ swaps }: Props) {
  const active = swaps.filter((s) => s.status === "open" || s.status === "pending_approval");

  if (active.length === 0) return null;

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">החלפות שלי</h2>
        <Link to="/swaps" className="text-sm text-indigo-600 hover:text-indigo-800">
          לדף החלפות →
        </Link>
      </div>
      <ul className="space-y-2">
        {active.map((s) => (
          <li key={s.id} className="flex items-center justify-between text-sm border-b dark:border-gray-600 last:border-0 pb-2 last:pb-0">
            <span className="text-gray-700">
              {new Date(s.duty_date).toLocaleDateString("he-IL")}
              {s.reason ? ` — ${s.reason}` : ""}
            </span>
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_CHIPS[s.status] ?? "bg-gray-100 text-gray-600"}`}>
              {STATUS_LABELS[s.status] ?? s.status}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
