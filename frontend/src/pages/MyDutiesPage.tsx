import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
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
import AskSwapModal from "../components/AskSwapModal";
import { useAuth } from "../auth/AuthContext";
import { listEffectiveDuties } from "../api/assignments";
import { getTransparency, getBreakdown, TransparencyRow } from "../api/scoring";
import { getReserveStats } from "../api/soldiers";
import { reportCannotAttend } from "../api/reserves";
import { getCalendarShift, CalendarShift } from "../api/calendar";
import DismissalModal from "../components/DismissalModal";
import { queryKeys } from "../queryKeys";
import { formatDateTimeIsrael, formatDutyRange, lastDutyDay } from "../utils/formatDate";

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
  const { t } = useTranslation();
  const { user } = useAuth();
  const [askSwapDuty, setAskSwapDuty] = useState<{
    assignment_id: string;
    start_date: string;
    end_date: string;
    duty_type_name: string;
  } | null>(null);
  const [absenceDuty, setAbsenceDuty] = useState<typeof askSwapDuty>(null);
  const [absenceReason, setAbsenceReason] = useState("");
  const [absenceError, setAbsenceError] = useState<string | null>(null);
  const [absenceSubmitting, setAbsenceSubmitting] = useState(false);
  const [gimelimShift, setGimelimShift] = useState<CalendarShift | null>(null);
  const [gimelimLoading, setGimelimLoading] = useState<string | null>(null);
  const [gimelimError, setGimelimError] = useState<string | null>(null);

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
  const gimelimPrimary = gimelimShift?.assignees.find((a) => a.soldier_id === user?.id && !a.is_reserve)
    ?? gimelimShift?.assignees[0];

  const loading = transparencyQuery.isLoading || breakdownQuery.isLoading || dutiesQuery.isLoading;
  // Both queries fetch required-object payloads (see api/scoring.ts) — a
  // malformed shape throws instead of silently rendering wrong totals.
  const hasScoreLoadError = transparencyQuery.isError || breakdownQuery.isError;

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

        {hasScoreLoadError && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {t("my_duties.load_error")}
          </p>
        )}

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
                    <td className="py-2">{formatDateTimeIsrael(a.created_at)}</td>
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
                          setAskSwapDuty({
                            assignment_id: d.assignment_id,
                            start_date: d.start_date,
                            end_date: d.end_date,
                            duty_type_name: d.duty_type_name,
                          })
                        }
                      >
                        בקש החלפה
                      </button>
                    </div>
                  )}
                  {!d.is_reserve && (
                    <div className="mt-1 flex flex-wrap gap-2">
                      <button
                        type="button"
                        data-testid={`report-absence-${d.assignment_id}`}
                        className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800 hover:bg-amber-200"
                        onClick={() => { setAbsenceDuty({ assignment_id: d.assignment_id, start_date: d.start_date, end_date: d.end_date, duty_type_name: d.duty_type_name }); setAbsenceReason(""); setAbsenceError(null); }}
                      >
                        לא יכול להגיע
                      </button>
                      {d.shift_id && (
                        <button
                          type="button"
                          data-testid={`report-gimelim-${d.assignment_id}`}
                          className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-800 hover:bg-red-200 disabled:opacity-50"
                          disabled={gimelimLoading === d.assignment_id}
                          onClick={async () => {
                            setGimelimLoading(d.assignment_id);
                            setGimelimError(null);
                            try {
                              setGimelimShift(await getCalendarShift(d.shift_id!));
                            } catch {
                              setGimelimError("לא ניתן לטעון את פרטי התורנות");
                            } finally {
                              setGimelimLoading(null);
                            }
                          }}
                        >
                          {gimelimLoading === d.assignment_id ? "טוען..." : "דווח גימלים"}
                        </button>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {askSwapDuty && (
          <AskSwapModal
            duty={askSwapDuty}
            dutyTypeName={askSwapDuty.duty_type_name}
            onClose={() => setAskSwapDuty(null)}
            onCreated={() => setAskSwapDuty(null)}
          />
        )}
        {absenceDuty && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true">
            <form
              dir="rtl"
              data-testid="absence-report-modal"
              className="w-full max-w-md space-y-4 rounded-lg bg-white p-5 shadow-xl dark:bg-gray-800"
              onSubmit={async (event) => {
                event.preventDefault();
                if (!user || !absenceReason.trim()) return;
                setAbsenceSubmitting(true);
                setAbsenceError(null);
                try {
                  await reportCannotAttend(absenceDuty.assignment_id, { from_date: absenceDuty.start_date, to_date: lastDutyDay(absenceDuty.end_date), reason: absenceReason.trim() });
                  await dutiesQuery.refetch();
                  setAbsenceDuty(null);
                } catch (error) {
                  setAbsenceError(error instanceof Error ? error.message : "לא ניתן לדווח על אי-התייצבות");
                } finally {
                  setAbsenceSubmitting(false);
                }
              }}
            >
              <h3 className="text-lg font-semibold">דיווח אי-יכולת להתייצב — {absenceDuty.duty_type_name}</h3>
              <p className="text-sm text-gray-600 dark:text-gray-300">{formatDutyRange(absenceDuty.start_date, absenceDuty.end_date)}</p>
              {absenceError && <p role="alert" className="text-sm text-red-600">{absenceError}</p>}
              <textarea
                required
                value={absenceReason}
                onChange={(event) => setAbsenceReason(event.target.value)}
                data-testid="absence-reason"
                placeholder="סיבה לדיווח"
                className="min-h-24 w-full rounded border p-2 dark:border-gray-600 dark:bg-gray-700"
              />
              <div className="flex justify-end gap-2">
                <button type="button" className="rounded border px-3 py-1.5 text-sm" onClick={() => setAbsenceDuty(null)}>ביטול</button>
                <button type="submit" data-testid="absence-submit" disabled={absenceSubmitting || !absenceReason.trim()} className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">{absenceSubmitting ? "שולח..." : "שלח דיווח"}</button>
              </div>
            </form>
          </div>
        )}
        {gimelimError && <p role="alert" className="text-sm text-red-600">{gimelimError}</p>}
        {gimelimShift && user && gimelimPrimary && (
          <DismissalModal
            shift={gimelimShift}
            primary={gimelimPrimary}
            canGimelim
            defaultRestDays={7}
            onClose={() => setGimelimShift(null)}
            onDone={() => { setGimelimShift(null); void dutiesQuery.refetch(); }}
          />
        )}
      </div>
    </Layout>
  );
}
