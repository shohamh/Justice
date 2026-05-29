import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { Breakdown, TransparencyRow, getBreakdown, getTransparency } from "../api/scoring";

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
        <table className="w-full text-sm text-right" data-testid="transparency-table">
          <thead>
            <tr className="border-b">
              <th className="p-1">{t("transparency.name")}</th>
              <th className="p-1">{t("transparency.unit")}</th>
              <th className="p-1">{t("transparency.enrolled_at")}</th>
              <th className="p-1">{t("transparency.active_days")}</th>
              <th className="p-1">{t("transparency.cumulative")}</th>
              <th className="p-1">{t("transparency.normalised")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.soldier_id} data-testid={`transparency-row-${r.soldier_id}`}
                  className={r.soldier_id === user?.id ? "bg-indigo-50" : ""}>
                <td className="p-1">
                  {r.soldier_id === user?.id ? (
                    <button className="text-indigo-600" onClick={toggleOwn} data-testid="own-row-toggle">{r.full_name}</button>
                  ) : r.full_name}
                </td>
                <td className="p-1">{r.node_name ?? "—"}</td>
                <td className="p-1">{r.enrolled_at}</td>
                <td className="p-1">{r.active_days}</td>
                <td className="p-1">{r.cumulative_score}</td>
                <td className="p-1">{r.normalised_score}</td>
              </tr>
            ))}
          </tbody>
        </table>
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
