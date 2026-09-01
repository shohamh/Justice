import { useTranslation } from "react-i18next";
import type { Alert } from "../api/commanderDashboard";
import SoldierLink from "./SoldierLink";

interface Props {
  data: Alert[] | null;
  scope?: "personal" | "command";
}

const severityColor: Record<string, string> = {
  warning: "text-yellow-700 dark:text-yellow-300 bg-yellow-50 dark:bg-yellow-950 border-yellow-200 dark:border-yellow-800",
  info: "text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800",
};

export default function AlertsPanel({ data, scope = "command" }: Props) {
  const { t } = useTranslation();
  const title =
    scope === "command"
      ? t("command_dashboard.alerts_scope_command")
      : t("home.alerts_scope_personal");
  return (
    <section className="space-y-2" aria-label={title}>
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{title}</p>
      {!data || data.length === 0 ? (
        <p className="text-gray-500">{t("command_dashboard.no_alerts")}</p>
      ) : (
        <div className="space-y-2" data-testid="alerts-panel">
          {data.map((a, i) => (
            <div key={i} className={`border rounded p-2 text-sm ${severityColor[a.severity] || "text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-700"}`}>
              <SoldierLink id={a.soldier_id} name={a.soldier_name} className="font-medium" />: {a.message}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
