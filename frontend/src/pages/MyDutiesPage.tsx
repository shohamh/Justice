import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { listEffectiveDuties } from "../api/assignments";
import { getTransparency, getBreakdown, TransparencyRow } from "../api/scoring";
import { getReserveStats } from "../api/soldiers";
import { queryKeys } from "../queryKeys";

function avg(rows: TransparencyRow[], key: "normalised_score" | "active_days" | "shift_count"): number {
  if (rows.length === 0) return 0;
  const vals = rows.map((r) => Number(r[key])).filter((v) => !isNaN(v));
  return vals.length === 0 ? 0 : vals.reduce((s, v) => s + v, 0) / vals.length;
}

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
}

function StatCard({ label, value, sub }: StatCardProps) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 text-center">
      <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</div>
      <div className="text-2xl font-bold text-indigo-700 dark:text-indigo-300">{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  );
}

const dayCount = (d: { start_date: string; end_date: string }) => {
  const [sy, sm, sd] = d.start_date.split("-").map(Number);
  const [ey, em, ed] = d.end_date.split("-").map(Number);
  return Math.max(1, (Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd)) / 86400000);
};

export default function MyDutiesPage() {
  const { user } = useAuth();

  const transparencyQuery = useQuery({
    queryKey: queryKeys.transparency(),
    queryFn: () => getTransparency().then((out) => out.rows),
  });
  const allRows = useMemo(() => transparencyQuery.data ?? [], [transparencyQuery.data]);

  const breakdownQuery = useQuery({
    queryKey: user ? queryKeys.breakdown(user.id) : ["breakdown", "anonymous"],
    queryFn: () => getBreakdown(user!.id),
    enabled: !!user,
  });
  const breakdown = breakdownQuery.data ?? null;

  const dutiesQuery = useQuery({
    queryKey: user ? queryKeys.effectiveDuties(user.id) : ["effectiveDuties", "anonymous"],
    queryFn: () => listEffectiveDuties(user!.id),
    enabled: !!user,
  });

  const reserveStatsQuery = useQuery({ queryKey: queryKeys.reserveStats(), queryFn: getReserveStats });
  const reserveStats = reserveStatsQuery.data ?? null;

  const today = new Date().toISOString().split("T")[0];
  // end_date is exclusive, so "over" means end_date is today or earlier.
  const pastDuties = (dutiesQuery.data ?? []).filter((d) => d.end_date <= today);
  const pastCount = pastDuties.length;
  const pastDays = pastDuties.reduce((s, d) => s + dayCount(d as { start_date: string; end_date: string }), 0);

  const loading = transparencyQuery.isLoading || breakdownQuery.isLoading || dutiesQuery.isLoading;

  const myRow = useMemo(
    () => allRows.find((r) => r.soldier_id === user?.id) ?? null,
    [allRows, user]
  );

  const unitAvgNormRaw = useMemo(() => avg(allRows, "normalised_score"), [allRows]);
  const unitAvgDays = useMemo(() => Math.round(avg(allRows, "active_days")), [allRows]);
  const unitAvgShifts = useMemo(() => Math.round(avg(allRows, "shift_count")), [allRows]);

  const rank = useMemo(() => {
    if (!myRow || allRows.length === 0) return null;
    const sorted = [...allRows].sort(
      (a, b) => Number(b.normalised_score) - Number(a.normalised_score)
    );
    const pos = sorted.findIndex((r) => r.soldier_id === myRow.soldier_id) + 1;
    return { pos, total: allRows.length };
  }, [myRow, allRows]);

  const typeChartData = useMemo(() => {
    if (!breakdown) return [];
    return breakdown.per_type
      .filter((p) => p.days > 0)
      .sort((a, b) => b.days - a.days)
      .map((p) => ({
        name: p.duty_type_name ?? p.duty_type_id.slice(0, 8),
        days: p.days,
        score: Number(p.score).toFixed(3),
      }));
  }, [breakdown]);

  const comparisonData = useMemo(
    () => [
      { name: "הניקוד שלי", value: Number(myRow?.normalised_score ?? 0) },
      { name: "ממוצע יחידה", value: unitAvgNormRaw },
    ],
    [myRow, unitAvgNormRaw]
  );

  if (loading) {
    return (
      <Layout>
        <div className="text-sm text-gray-500 animate-pulse text-center mt-16" dir="rtl">
          טוען...
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div
        className="space-y-6 max-w-3xl mx-auto"
        dir="rtl"
        data-testid="my-diary-page"
      >
        <h2 className="text-xl font-semibold">היומן שלי</h2>

        {/* Section 1: Stat cards */}
        <div
          className="grid grid-cols-2 sm:grid-cols-4 gap-3"
          data-testid="my-diary-stat-cards"
        >
          <StatCard
            label="תורנויות שירתתי"
            value={pastCount}
            sub={`ממוצע יחידה: ${unitAvgShifts}`}
          />
          <StatCard
            label="ימי תורנות"
            value={pastDays}
            sub={`ממוצע יחידה: ${unitAvgDays}`}
          />
          <StatCard
            label="ניקוד מנורמל"
            value={Number(myRow?.normalised_score ?? 0).toFixed(3)}
            sub={`ממוצע יחידה: ${unitAvgNormRaw.toFixed(3)}`}
          />
          <StatCard
            label="דירוג ביחידה"
            value={rank ? `${rank.pos} מתוך ${rank.total}` : "—"}
          />
          {reserveStats && (
            <StatCard
              label="ימי רזרבה (חלון נוכחי)"
              value={`${reserveStats.used_days} / ${reserveStats.max_days}`}
              sub={`חלון של ${reserveStats.window_days} ימים`}
            />
          )}
        </div>

        {/* Section 2: Breakdown by duty type */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
          <h3 className="font-medium text-sm">פירוט לפי סוג תורנות</h3>
          {typeChartData.length === 0 ? (
            <p className="text-sm text-gray-500">אין נתוני פירוט</p>
          ) : (
            <ResponsiveContainer
              width="100%"
              height={Math.max(typeChartData.length * 44, 100)}
            >
              <BarChart
                data={typeChartData}
                layout="vertical"
                margin={{ top: 0, right: 30, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={110}
                  tick={{ fontSize: 11 }}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const item = payload[0].payload as { days: number; score: string };
                    return (
                      <div className="bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded px-2 py-1 text-xs shadow">
                        {item.days} ימים (ניקוד: {item.score})
                      </div>
                    );
                  }}
                />
                <Bar dataKey="days" fill="#6366f1" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Section 3: Score vs unit average */}
        {allRows.length > 1 && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
            <h3 className="font-medium text-sm">ניקוד מנורמל — אני מול הממוצע</h3>
            <ResponsiveContainer width="100%" height={140}>
              <BarChart
                data={comparisonData}
                margin={{ top: 0, right: 30, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip
                  formatter={(v) => [Number(v ?? 0).toFixed(3), "ניקוד מנורמל"]}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  <Cell fill="#6366f1" />
                  <Cell fill="#9ca3af" />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Section 4: Manual score adjustments */}
        {breakdown && breakdown.adjustments.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
            <h3 className="font-medium text-sm">התאמות ניקוד ידניות</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-gray-600">
                  <th className="text-right pb-2 font-medium">תאריך</th>
                  <th className="text-right pb-2 font-medium">שינוי</th>
                  <th className="text-right pb-2 font-medium">סיבה</th>
                </tr>
              </thead>
              <tbody>
                {breakdown.adjustments.map((a) => (
                  <tr key={a.id} className="border-b dark:border-gray-600 last:border-0">
                    <td className="py-2">{a.created_at.slice(0, 10)}</td>
                    <td
                      className={`py-2 font-medium ${
                        Number(a.delta) >= 0 ? "text-green-600" : "text-red-600"
                      }`}
                    >
                      {Number(a.delta) >= 0 ? "+" : ""}
                      {Number(a.delta).toFixed(3)}
                    </td>
                    <td className="py-2">{a.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  );
}
