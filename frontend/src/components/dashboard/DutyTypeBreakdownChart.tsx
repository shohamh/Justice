import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";

export interface BreakdownPerType {
  duty_type_id: string;
  duty_type_name: string | null;
  days: number;
  days_past: number;
  days_future: number;
  score: string;
}

interface Props {
  perType: BreakdownPerType[];
  /**
   * HomePage renders this chart RTL-mirrored (axis reversed, category labels on the
   * right); MyDutiesPage renders it in the default (unmirrored) recharts layout. This
   * preserves each page's existing visual behavior exactly rather than changing either
   * page's look as a side effect of the shared-component extraction.
   */
  mirrored?: boolean;
}

const PAST_COLOR = "#6366f1";
const FUTURE_COLOR = "#a5b4fc";
const PAST_KEY = "ימים שבוצעו";
const FUTURE_KEY = "ימים עתידיים";

export default function DutyTypeBreakdownChart({ perType, mirrored = false }: Props) {
  const typeChartData = perType
    .filter((p) => p.days > 0)
    .sort((a, b) => b.days - a.days)
    .map((p) => ({
      name: p.duty_type_name ?? p.duty_type_id.slice(0, 8),
      [PAST_KEY]: p.days_past,
      [FUTURE_KEY]: p.days_future,
      score: Number(p.score).toFixed(3),
    }));

  const outerRadius: [number, number, number, number] = mirrored ? [4, 0, 0, 4] : [0, 4, 4, 0];

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
      <h3 className="font-medium text-sm">פירוט לפי סוג תורנות</h3>
      {typeChartData.length === 0 ? (
        <p className="text-sm text-gray-500">אין נתוני פירוט</p>
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(typeChartData.length * 44, 100)}>
          <BarChart
            data={typeChartData}
            layout="vertical"
            margin={mirrored ? { top: 0, right: 0, left: 30, bottom: 0 } : { top: 0, right: 30, left: 0, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" reversed={mirrored} tick={{ fontSize: 11 }} />
            <YAxis
              type="category"
              dataKey="name"
              orientation={mirrored ? "right" : "left"}
              width={110}
              tick={{ fontSize: 11 }}
            />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const item = payload[0].payload as {
                  [PAST_KEY]: number;
                  [FUTURE_KEY]: number;
                  score: string;
                };
                return (
                  <div className="bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded px-2 py-1 text-xs shadow space-y-0.5">
                    <div>{PAST_KEY}: {item[PAST_KEY]}</div>
                    <div>{FUTURE_KEY}: {item[FUTURE_KEY]}</div>
                    <div>ניקוד: {item.score}</div>
                  </div>
                );
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey={PAST_KEY} stackId="days" fill={PAST_COLOR} />
            <Bar dataKey={FUTURE_KEY} stackId="days" fill={FUTURE_COLOR} radius={outerRadius} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
