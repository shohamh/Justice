import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import AlertBanners from "../components/dashboard/AlertBanners";
import DutyCalendarWidget from "../components/dashboard/DutyCalendarWidget";
import DutyDetailModal from "../components/dashboard/DutyDetailModal";
import UpcomingDutiesWidget from "../components/dashboard/UpcomingDutiesWidget";
import UpcomingRangesWidget from "../components/dashboard/UpcomingRangesWidget";
import SwapStatusWidget from "../components/dashboard/SwapStatusWidget";
import PendingApprovalsWidget from "../components/dashboard/PendingApprovalsWidget";
import DutyHistoryWidget from "../components/dashboard/DutyHistoryWidget";
import DutyTypeBreakdownChart from "../components/dashboard/DutyTypeBreakdownChart";

import { useAuth } from "../auth/AuthContext";
import { usePublicSettings } from "../hooks/usePublicSettings";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { listDutyTypes, listLocations } from "../api/dutyConfig";
import { listMySwaps, listPendingSwaps } from "../api/swaps";
import { listPendingEnrollments } from "../api/enrollment";
import { SettingsMap, getSystemSettings } from "../api/systemSettings";
import { getTransparency, getBreakdown } from "../api/scoring";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import { getRanges } from "../api/ranges";
import { lastDutyDay } from "../utils/formatDate";

function offsetDate(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().split("T")[0];
}

// end_date is exclusive (the first day NOT touched), so no +1 here.
function dayCount(d: { start_date: string; end_date: string }): number {
  const [sy, sm, sd] = d.start_date.split("-").map(Number);
  const [ey, em, ed] = d.end_date.split("-").map(Number);
  return (Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd)) / 86400000;
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 text-center">
      <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</div>
      <div className="text-2xl font-bold text-indigo-700 dark:text-indigo-300">{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  );
}

export default function HomePage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const publicSettings = usePublicSettings();

  const [selectedDuty, setSelectedDuty] = useState<EffectiveDuty | null>(null);

  const canApprove = user?.role === "admin" || user?.is_commander || user?.is_duty_manager;

  const dutiesQuery = useQuery({
    queryKey: user ? queryKeys.effectiveDuties(user.id, { date_from: offsetDate(-365), date_to: offsetDate(60) }) : ["effectiveDuties", "anonymous"],
    queryFn: () => listEffectiveDuties(user!.id, { date_from: offsetDate(-365), date_to: offsetDate(60) }),
    enabled: !!user,
  });
  const duties = useMemo(() => dutiesQuery.data ?? [], [dutiesQuery.data]);

  const typesQuery = useQuery({ queryKey: queryKeys.dutyTypes(), queryFn: listDutyTypes });
  const typeNames = Object.fromEntries((typesQuery.data ?? []).map((t) => [t.id, t.name]));

  const locsQuery = useQuery({ queryKey: queryKeys.dutyLocations(), queryFn: listLocations });
  const locationNames = Object.fromEntries((locsQuery.data ?? []).map((l) => [l.id, l.name]));

  const mySwapsQuery = useQuery({ queryKey: queryKeys.mySwaps(), queryFn: listMySwaps });
  const mySwaps = mySwapsQuery.data ?? [];

  const settingsQuery = useQuery({ queryKey: queryKeys.systemSettings(), queryFn: getSystemSettings });
  const settings = settingsQuery.data ?? ({} as SettingsMap);

  const rangesQuery = useQuery({
    queryKey: queryKeys.ranges(),
    queryFn: () => getRanges(user!.hierarchy_node_id as string),
    enabled: !!user?.hierarchy_node_id,
  });
  const ranges = rangesQuery.data ?? [];

  const transparencyQuery = useQuery({
    queryKey: queryKeys.transparency(),
    queryFn: getTransparency,
    select: (out) => out.rows,
  });
  const transparencyRows = useMemo(() => transparencyQuery.data ?? [], [transparencyQuery.data]);

  const breakdownQuery = useQuery({
    queryKey: user ? queryKeys.breakdown(user.id) : ["breakdown", "anonymous"],
    queryFn: () => getBreakdown(user!.id),
    enabled: !!user,
  });
  const breakdown = breakdownQuery.data ?? null;

  const enrollQuery = useQuery({
    queryKey: queryKeys.pendingEnrollments(),
    queryFn: listPendingEnrollments,
    enabled: canApprove,
  });
  const pendingEnrollments = enrollQuery.data ?? [];

  const pendingSwapsQuery = useQuery({
    queryKey: queryKeys.pendingSwaps(),
    queryFn: listPendingSwaps,
    enabled: canApprove,
  });
  const pendingSwaps = pendingSwapsQuery.data ?? [];

  const pendingConstraintsQuery = useQuery({
    queryKey: queryKeys.pendingConstraintsCount(),
    queryFn: getPendingCount,
    enabled: canApprove,
  });
  const pendingConstraints = pendingConstraintsQuery.data ?? 0;

  const pendingExemptionsQuery = useQuery({
    queryKey: queryKeys.pendingExemptionsCount(),
    queryFn: getPendingExemptionCount,
    enabled: canApprove,
  });
  const pendingExemptions = pendingExemptionsQuery.data ?? 0;

  const pendingFieldUpdatesQuery = useQuery({
    queryKey: queryKeys.pendingFieldUpdatesCount(),
    queryFn: getPendingFieldUpdateCount,
    enabled: canApprove,
  });
  const pendingFieldUpdates = pendingFieldUpdatesQuery.data ?? 0;

  function handleOpenDuty(duty: EffectiveDuty) {
    setSelectedDuty(duty);
  }

  function handleRequestSwap(duty: EffectiveDuty) {
    setSelectedDuty(null);
    navigate(`/swaps?new=${duty.assignment_id}`);
  }

  const myRow = useMemo(
    () => transparencyRows.find((r) => r.soldier_id === user?.id) ?? null,
    [transparencyRows, user],
  );

  const today = new Date().toISOString().split("T")[0];

  const pastDuties = useMemo(
    // end_date is exclusive, so a duty whose last day is today has end_date === today+1;
    // "over" means end_date is today or earlier.
    () => duties.filter((d) => d.end_date <= today),
    [duties, today],
  );
  const pastCount = pastDuties.length;
  const pastDays = useMemo(
    () => pastDuties.reduce((s, d) => s + dayCount(d), 0),
    [pastDuties],
  );

  const unitAvgNormRaw = useMemo(() => {
    if (transparencyRows.length === 0) return 0;
    return transparencyRows.reduce((s, r) => s + Number(r.normalised_score), 0) / transparencyRows.length;
  }, [transparencyRows]);

  const unitAvgDays = useMemo(() => {
    if (transparencyRows.length === 0) return 0;
    return Math.round(transparencyRows.reduce((s, r) => s + Number(r.active_days), 0) / transparencyRows.length);
  }, [transparencyRows]);

  const unitAvgShifts = useMemo(() => {
    if (transparencyRows.length === 0) return 0;
    return Math.round(transparencyRows.reduce((s, r) => s + Number(r.shift_count), 0) / transparencyRows.length);
  }, [transparencyRows]);

  const rank = useMemo(() => {
    if (!myRow || transparencyRows.length === 0) return null;
    const sorted = [...transparencyRows].sort(
      (a, b) => Number(b.normalised_score) - Number(a.normalised_score),
    );
    const pos = sorted.findIndex((r) => r.soldier_id === myRow.soldier_id) + 1;
    return { pos, total: transparencyRows.length };
  }, [myRow, transparencyRows]);

  const currentMonthStart = useMemo(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
  }, []);

  const currentMonthEnd = useMemo(() => {
    const d = new Date();
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    return last.toISOString().split("T")[0];
  }, []);

  const monthReserveDays = useMemo(() => {
    return duties
      .filter(
        (d) =>
          d.is_reserve &&
          d.start_date <= currentMonthEnd &&
          d.end_date > currentMonthStart
      )
      .reduce((sum, d) => {
        const dutyLastDay = lastDutyDay(d.end_date);
        const start = d.start_date < currentMonthStart ? currentMonthStart : d.start_date;
        const end = dutyLastDay > currentMonthEnd ? currentMonthEnd : dutyLastDay;
        const [sy, sm, sd] = start.split("-").map(Number);
        const [ey, em, ed] = end.split("-").map(Number);
        const days = (Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd)) / 86400000 + 1;
        return sum + Math.max(0, days);
      }, 0);
  }, [duties, currentMonthStart, currentMonthEnd]);

  const yearReserveDays = useMemo(() => {
    const yearStart = `${new Date().getFullYear()}-01-01`;
    const yearEnd = `${new Date().getFullYear()}-12-31`;
    return duties
      .filter(
        (d) =>
          d.is_reserve &&
          d.start_date <= yearEnd &&
          d.end_date > yearStart
      )
      .reduce((sum, d) => {
        const dutyLastDay = lastDutyDay(d.end_date);
        const start = d.start_date < yearStart ? yearStart : d.start_date;
        const end = dutyLastDay > yearEnd ? yearEnd : dutyLastDay;
        const [sy, sm, sd] = start.split("-").map(Number);
        const [ey, em, ed] = end.split("-").map(Number);
        const days = (Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd)) / 86400000 + 1;
        return sum + Math.max(0, days);
      }, 0);
  }, [duties]);

  const comparisonData = useMemo(
    () => [
      // recharts always lays categories out left-to-right regardless of page
      // dir, so "average" (read second in RTL) goes first in the array —
      // that puts "my score" on the visual right, where RTL reading starts.
      { name: "ממוצע יחידה", value: unitAvgNormRaw },
      { name: "הניקוד שלי", value: Number(myRow?.normalised_score ?? 0) },
    ],
    [myRow, unitAvgNormRaw],
  );

  return (
    <Layout>
      <div className="space-y-4 max-w-3xl mx-auto" dir="rtl">
        <h2 className="text-xl font-semibold">{t("home.welcome", { name: user?.full_name ?? "" })}</h2>

        <AlertBanners
          lastMitvahimDate={user?.last_mitvahim_date ?? null}
          lastAlalDate={user?.last_alal_date ?? null}
          settings={settings}
        />

        <DutyCalendarWidget duties={duties} typeNames={typeNames} onOpenDuty={handleOpenDuty} />

        <UpcomingDutiesWidget
          duties={duties}
          typeNames={typeNames}
          locationNames={locationNames}
          onOpenDuty={handleOpenDuty}
        />

        {publicSettings?.["mitvachim.enabled"] === true && (
          <UpcomingRangesWidget
            ranges={ranges}
            onOpenRange={(range) => navigate(`/ranges?event=${range.id}`)}
          />
        )}

        <SwapStatusWidget swaps={mySwaps} />

        {canApprove && (
          <PendingApprovalsWidget
            pendingEnrollments={pendingEnrollments}
            pendingSwaps={pendingSwaps}
            pendingConstraints={pendingConstraints}
            pendingExemptions={pendingExemptions}
            pendingFieldUpdates={pendingFieldUpdates}
          />
        )}

        <DutyHistoryWidget
          duties={duties}
          typeNames={typeNames}
          locationNames={locationNames}
          myRow={myRow}
          allRows={transparencyRows}
        />

        {/* Reserve days this month */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-500 dark:text-gray-400">ימי רזרבה החודש</p>
            <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">{monthReserveDays}</p>
            <p className="text-xs text-gray-400 mt-0.5">{"סה\"כ"} השנה: {yearReserveDays}</p>
          </div>
        </div>

        {/* היומן שלי — stat cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
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
        </div>

        {/* Breakdown by duty type */}
        <DutyTypeBreakdownChart perType={breakdown?.per_type ?? []} mirrored />

        {/* Score vs unit average */}
        {transparencyRows.length > 1 && (
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
                <Tooltip formatter={(v) => [Number(v ?? 0).toFixed(3), "ניקוד מנורמל"]} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  <Cell fill="#9ca3af" />
                  <Cell fill="#6366f1" />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Manual score adjustments */}
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

      <DutyDetailModal
        duty={selectedDuty}
        typeNames={typeNames}
        locationNames={locationNames}
        onClose={() => setSelectedDuty(null)}
        onRequestSwap={handleRequestSwap}
      />
    </Layout>
  );
}
