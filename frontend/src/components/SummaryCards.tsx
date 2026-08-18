import { useTranslation } from "react-i18next";
import type { SummaryCards as SummaryCardsData } from "../api/commanderDashboard";

interface Props {
  data: SummaryCardsData | null;
}

export default function SummaryCards({ data }: Props) {
  const { t } = useTranslation();
  if (!data) return null;
  return (
    <div className="flex gap-4 mb-6" data-testid="summary-cards">
      <div className="flex-1 bg-white dark:bg-gray-800 rounded-lg shadow p-4 text-right" data-testid="card-approvals">
        <div className="text-2xl font-bold">{data.approvals_pending}</div>
        <div className="text-sm text-gray-500">{t("command_dashboard.approvals_pending")}</div>
      </div>
      <div className="flex-1 bg-white dark:bg-gray-800 rounded-lg shadow p-4 text-right" data-testid="card-upcoming">
        <div className="text-2xl font-bold">{data.upcoming_duties_7d}</div>
        {data.unfilled_gaps > 0 && <span className="text-xs text-red-500 mr-1">({data.unfilled_gaps} {t("command_dashboard.gaps")})</span>}
        <div className="text-sm text-gray-500">{t("command_dashboard.upcoming_7d")}</div>
      </div>
      <div className="flex-1 bg-white dark:bg-gray-800 rounded-lg shadow p-4 text-right" data-testid="card-alerts">
        <div className="text-2xl font-bold">{data.alerts_count}</div>
        <div className="text-sm text-gray-500">{t("command_dashboard.alerts")}</div>
      </div>
    </div>
  );
}
