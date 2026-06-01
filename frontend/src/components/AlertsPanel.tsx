import { useTranslation } from "react-i18next";
import type { Alert } from "../api/commanderDashboard";

interface Props {
  data: Alert[] | null;
}

const severityColor: Record<string, string> = {
  warning: "text-yellow-700 bg-yellow-50 border-yellow-200",
  info: "text-blue-700 bg-blue-50 border-blue-200",
};

export default function AlertsPanel({ data }: Props) {
  const { t } = useTranslation();
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_alerts")}</p>;
  return (
    <div className="space-y-2" data-testid="alerts-panel">
      {data.map((a, i) => (
        <div key={i} className={`border rounded p-2 text-sm ${severityColor[a.severity] || "text-gray-700 bg-gray-50"}`}>
          <span className="font-medium">{a.soldier_name}</span>: {a.message}
        </div>
      ))}
    </div>
  );
}
