import { useTranslation } from "react-i18next";
import type { FairnessStats, NodeFairness } from "../api/commanderDashboard";

interface InternalProps {
  data: FairnessStats | null;
}

interface ExternalProps {
  data: NodeFairness[] | null;
}

export function InternalFairness({ data }: InternalProps) {
  const { t } = useTranslation();
  if (!data || data.soldier_count === 0) return <p className="text-gray-500">{t("command_dashboard.no_fairness_data")}</p>;
  return (
    <div className="space-y-1 text-sm" data-testid="internal-fairness">
      <div className="grid grid-cols-3 gap-2">
        <div><span className="text-gray-500">{t("command_dashboard.mean")}:</span> <strong>{data.mean}</strong></div>
        <div><span className="text-gray-500">{t("command_dashboard.median")}:</span> <strong>{data.median}</strong></div>
        <div><span className="text-gray-500">{t("command_dashboard.stddev")}:</span> <strong>{data.stddev}</strong></div>
        <div><span className="text-gray-500">{t("command_dashboard.min")}:</span> <strong>{data.min}</strong></div>
        <div><span className="text-gray-500">{t("command_dashboard.max")}:</span> <strong>{data.max}</strong></div>
        <div><span className="text-gray-500">{t("command_dashboard.soldiers")}:</span> <strong>{data.soldier_count}</strong></div>
      </div>
    </div>
  );
}

export function ExternalFairness({ data }: ExternalProps) {
  const { t } = useTranslation();
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_peers")}</p>;
  return (
    <div className="overflow-x-auto" data-testid="external-fairness">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="text-right p-1">{t("command_dashboard.unit")}</th>
            <th className="text-right p-1">{t("command_dashboard.mean")}</th>
            <th className="text-right p-1">{t("command_dashboard.median")}</th>
            <th className="text-right p-1">{t("command_dashboard.stddev")}</th>
            <th className="text-right p-1">{t("command_dashboard.soldiers")}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((n) => (
            <tr key={n.node_id} className="border-b hover:bg-gray-50">
              <td className="p-1 font-medium">{n.node_name}</td>
              <td className="p-1">{n.stats.mean}</td>
              <td className="p-1">{n.stats.median}</td>
              <td className="p-1">{n.stats.stddev}</td>
              <td className="p-1">{n.stats.soldier_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
