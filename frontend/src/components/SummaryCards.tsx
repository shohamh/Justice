import { useTranslation } from "react-i18next";
import type { SummaryCards as SummaryCardsData } from "../api/commanderDashboard";

interface Props {
  data: SummaryCardsData | null;
  onCardClick: (panel: string) => void;
}

export default function SummaryCards({ data, onCardClick }: Props) {
  const { t } = useTranslation();
  if (!data) return null;
  return (
    <div className="flex gap-4 mb-6" data-testid="summary-cards">
      <button onClick={() => onCardClick("approvals")} className="flex-1 bg-white rounded-lg shadow p-4 text-right hover:bg-gray-50" data-testid="card-approvals">
        <div className="text-2xl font-bold">{data.approvals_pending}</div>
        <div className="text-sm text-gray-500">{t("command_dashboard.approvals_pending")}</div>
      </button>
      <button onClick={() => onCardClick("upcoming")} className="flex-1 bg-white rounded-lg shadow p-4 text-right hover:bg-gray-50" data-testid="card-upcoming">
        <div className="text-2xl font-bold">{data.upcoming_duties_7d}</div>
        {data.unfilled_gaps > 0 && <span className="text-xs text-red-500 mr-1">({data.unfilled_gaps} {t("command_dashboard.gaps")})</span>}
        <div className="text-sm text-gray-500">{t("command_dashboard.upcoming_7d")}</div>
      </button>
      <button onClick={() => onCardClick("alerts")} className="flex-1 bg-white rounded-lg shadow p-4 text-right hover:bg-gray-50" data-testid="card-alerts">
        <div className="text-2xl font-bold">{data.alerts_count}</div>
        <div className="text-sm text-gray-500">{t("command_dashboard.alerts")}</div>
      </button>
    </div>
  );
}
