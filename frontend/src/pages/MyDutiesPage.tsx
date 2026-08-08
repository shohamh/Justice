import { useMemo, useState } from "react";
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
import DutyTypeBreakdownChart from "../components/dashboard/DutyTypeBreakdownChart";
import OfferSwapModal from "../components/OfferSwapModal";
import { useAuth } from "../auth/AuthContext";
import { listEffectiveDuties } from "../api/assignments";
import { getTransparency, getBreakdown, TransparencyRow } from "../api/scoring";
import { getReserveStats } from "../api/soldiers";
import { queryKeys } from "../queryKeys";
import { formatDutyRange } from "../utils/formatDate";

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
  const [offerSwapTarget, setOfferSwapTarget] = useState<{
    soldierId: string;
    soldierName: string;
    assignmentId: string;
    dutyStart: string;
    dutyEnd: string;
    dutyTypeId: string;
  } | null>(null);

  const transparencyQuery = useQuery({
    queryKey: queryKeys.transparency(),
    queryFn: getTransparency,
    select: (out) => out.rows,
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

  // Duties still ahead of the soldier (end_date is exclusive, so end_date > today
  // means the last worked day is today or later).
  const upcomingDuties = (dutiesQuery.data ?? [])
    .filter((d) => d.end_date > today)
    .sort((a, b) => a.start_date.localeCompare(b.start_date));

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
            label="תורנויות שביצעתי"
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
            sub="מיקום 1 = הניקוד המנורמל הגבוה ביותר ביחידה (הכי הרבה תורנויות ביחס לימים הפעילים)"
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
        <DutyTypeBreakdownChart perType={breakdown?.per_type ?? []} />

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

        {/* Section 5: Upcoming duties */}
        {upcomingDuties.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
            <h3 className="font-medium text-sm">תורנויות קרובות</h3>
            <ul className="space-y-3">
              {upcomingDuties.map((d) => (
                <li key={`${d.assignment_id}-${d.start_date}`} className="border-b dark:border-gray-600 last:border-0 pb-2 last:pb-0">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium">{d.duty_type_name}</span>
                    <span className="text-gray-500 dark:text-gray-400">
                      {formatDutyRange(d.start_date, d.end_date)}
                    </span>
                  </div>
                  {d.weapon_ineligible && (
                    <div className="mt-1 flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
                      <span>⚠️ {d.weapon_ineligible_reason ?? "אינך כשיר לתורנות זו"}</span>
                      <button
                        className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded hover:bg-red-200"
                        onClick={() =>
                          setOfferSwapTarget({
                            soldierId: d.soldier_id,
                            soldierName: user!.full_name,
                            assignmentId: d.assignment_id,
                            dutyStart: d.start_date,
                            dutyEnd: d.end_date,
                            dutyTypeId: d.duty_type_id,
                          })
                        }
                      >
                        בקש החלפה
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {offerSwapTarget && (
          <OfferSwapModal
            targetSoldierId={offerSwapTarget.soldierId}
            targetSoldierName={offerSwapTarget.soldierName}
            targetAssignmentId={offerSwapTarget.assignmentId}
            targetDutyStart={offerSwapTarget.dutyStart}
            targetDutyEnd={offerSwapTarget.dutyEnd}
            targetDutyTypeId={offerSwapTarget.dutyTypeId}
            onClose={() => setOfferSwapTarget(null)}
            onDone={() => setOfferSwapTarget(null)}
          />
        )}
      </div>
    </Layout>
  );
}
