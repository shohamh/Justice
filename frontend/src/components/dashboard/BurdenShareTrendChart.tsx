import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import type { BurdenShareQuarterRow } from "../../api/scoring";

interface Props {
  quarters: BurdenShareQuarterRow[];
}

export default function BurdenShareTrendChart({ quarters }: Props) {
  const data = quarters.map((q) => ({
    name: q.quarter_label,
    value: Number(q.share) * 100,
    isPartial: q.is_partial,
  }));

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
      <h3 className="font-medium text-sm">חלק בנטל לאורך זמן</h3>
      {data.length === 0 ? (
        <p className="text-sm text-gray-500">אין עדיין נתוני מגמה</p>
      ) : (
        <ResponsiveContainer width="100%" height={140}>
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} unit="%" />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const item = payload[0].payload as { value: number; isPartial: boolean };
                return (
                  <div className="bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded px-2 py-1 text-xs shadow">
                    חלק בנטל: {item.value.toFixed(1)}%{item.isPartial ? " (רבעון חלקי)" : ""}
                  </div>
                );
              }}
            />
            <Line type="monotone" dataKey="value" stroke="#6366f1" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
