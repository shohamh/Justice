import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { Breakdown, TransparencyRow, getBreakdown, getTransparency } from "../api/scoring";
import { DataTable, type ColDef } from "../components/DataTable";

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

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="transparency-page">
        <h2 className="text-xl font-semibold">{t("transparency.title")}</h2>
        {(() => {
          const transCols: ColDef<TransparencyRow>[] = [
            {
              id: "name",
              header: t("transparency.name"),
              cell: (r) =>
                r.soldier_id === user?.id ? (
                  <button className="text-indigo-600" onClick={toggleOwn} data-testid="own-row-toggle">
                    {r.full_name}
                  </button>
                ) : (
                  r.full_name
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
              id: "normalised",
              header: t("transparency.normalised"),
              cell: (r) => r.normalised_score,
              sortValue: (r) => Number(r.normalised_score),
            },
          ];
          return (
            <DataTable
              columns={transCols}
              data={rows}
              filterPlaceholder={t("table.filter_placeholder")}
              rowClassName={(r) => (r.soldier_id === user?.id ? "bg-indigo-50" : "")}
            />
          );
        })()}
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
