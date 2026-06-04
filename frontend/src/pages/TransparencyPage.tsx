import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { Breakdown, TransparencyRow, getBreakdown, getTransparency } from "../api/scoring";
import { DataTable, type ColDef } from "../components/DataTable";
import SoldierLink from "../components/SoldierLink";

export default function TransparencyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [rows, setRows] = useState<TransparencyRow[]>([]);
  const [breakdown, setBreakdown] = useState<Breakdown | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => { void getTransparency().then(setRows); }, []);

  async function toggleOwn() {
    if (!expanded && user) setBreakdown(await getBreakdown(user.id));
    setExpanded(!expanded);
  }

  const avgActiveDays = useMemo(() => {
    if (rows.length === 0) return 0;
    return Math.round(rows.reduce((s, r) => s + r.active_days, 0) / rows.length);
  }, [rows]);

  const avgCumulative = useMemo(() => {
    if (rows.length === 0) return 0;
    return rows.reduce((s, r) => s + Number(r.cumulative_score), 0) / rows.length;
  }, [rows]);

  const avgNormalised = useMemo(() => {
    if (rows.length === 0) return 0;
    return rows.reduce((s, r) => s + Number(r.normalised_score), 0) / rows.length;
  }, [rows]);

  const avgScorePerDay = useMemo(() => {
    if (rows.length === 0) return 0;
    return rows.reduce((s, r) => s + Number(r.score_per_day), 0) / rows.length;
  }, [rows]);

  const transCols: ColDef<TransparencyRow>[] = [
    {
      id: "name",
      header: t("transparency.name"),
      cell: (r) =>
        r.soldier_id === user?.id ? (
          <button className="text-indigo-600 dark:text-indigo-400" onClick={toggleOwn} data-testid="own-row-toggle">
            {r.full_name}
          </button>
        ) : (
          <SoldierLink id={r.soldier_id} name={r.full_name} />
        ),
      sortValue: (r) => r.full_name,
      filterValue: (r) => r.full_name,
    },
    {
      id: "unit",
      header: t("transparency.unit"),
      cell: (r) => r.node_name ?? "—",
      sortValue: (r) => r.node_name ?? "",
      filterValue: (r) => r.node_name ?? "",
    },
    {
      id: "enrolled_at",
      header: t("transparency.enrolled_at"),
      cell: (r) => r.enrolled_at,
      sortValue: (r) => r.enrolled_at,
    },
    {
      id: "active_days",
      header: t("transparency.active_days"),
      cell: (r) => r.active_days,
      sortValue: (r) => r.active_days,
    },
    {
      id: "cumulative",
      header: t("transparency.cumulative"),
      cell: (r) => r.cumulative_score,
      sortValue: (r) => Number(r.cumulative_score),
    },
    {
      id: "score_per_day",
      header: t("transparency.score_per_day"),
      headerTooltip: `${t("transparency.score_per_day_modal_title")}\n\n${t("transparency.score_per_day_modal_body")}`,
      cell: (r) => { const n = Number(r.score_per_day); return isNaN(n) ? r.score_per_day : n.toFixed(3); },
      sortValue: (r) => Number(r.score_per_day),
    },
    {
      id: "normalised",
      header: t("transparency.normalised"),
      headerTooltip: t("transparency.normalised_tooltip"),
      cell: (r) => { const n = Number(r.normalised_score); return isNaN(n) ? r.normalised_score : n.toFixed(3); },
      sortValue: (r) => Number(r.normalised_score),
    },
  ];

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" data-testid="transparency-page">
        <h2 className="text-xl font-semibold">{t("transparency.title")}</h2>

        {/* Summary cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" dir="rtl">
          <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-center">
            <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.avg_active_days")}</p>
            <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">{avgActiveDays}</p>
          </div>
          <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-center">
            <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.avg_cumulative")}</p>
            <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">{avgCumulative.toFixed(2)}</p>
          </div>
          <div className={`rounded-lg p-3 border text-center ${avgScorePerDay > 0.3 ? "bg-red-50 dark:bg-red-950 border-red-300 dark:border-red-700" : "bg-gray-50 dark:bg-gray-700 border-gray-200 dark:border-gray-600"}`}>
            <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.score_per_day")} ממוצע</p>
            <p className={`text-lg font-semibold ${avgScorePerDay > 0.3 ? "text-red-600 dark:text-red-400" : "text-gray-800 dark:text-gray-100"}`}>{avgScorePerDay.toFixed(3)}</p>
            {avgScorePerDay > 0.3 && <p className="text-xs text-red-500 mt-0.5">עומס תורנויות חמור</p>}
          </div>
          <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-center">
            <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.avg_normalised")}</p>
            <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">{avgNormalised.toFixed(3)}</p>
          </div>
        </div>

        <DataTable
          columns={transCols}
          data={rows}
          filterPlaceholder={t("table.filter_placeholder")}
          rowClassName={(r) => (r.soldier_id === user?.id ? "bg-indigo-50 dark:bg-indigo-950" : "")}
        />

        {expanded && breakdown && (
          <div data-testid="own-breakdown" className="border-t pt-3 text-sm">
            <h3 className="font-medium">{t("transparency.my_breakdown")}</h3>
            <ul>
              {breakdown.per_type.map((pt) => (
                <li key={pt.duty_type_id}>{pt.duty_type_name ?? pt.duty_type_id}: {pt.days} {t("transparency.days")} — {pt.score}</li>
              ))}
            </ul>
            <h4 className="font-medium mt-2">{t("transparency.adjustments")}</h4>
            <ul>
              {breakdown.adjustments.map((a) => <li key={a.id}>{a.delta} — {a.reason}</li>)}
            </ul>
          </div>
        )}
      </section>
    </Layout>
  );
}
