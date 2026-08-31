import { useTranslation } from "react-i18next";
import type { PotentialCount } from "../api/commanderDashboard";

interface Props {
  data: PotentialCount[] | null;
}

export default function DutyPotentialPanel({ data }: Props) {
  const { t } = useTranslation();
  if (!data || data.length === 0) return <p className="text-gray-500 dark:text-gray-400">{t("command_dashboard.no_potential_data")}</p>;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3" data-testid="duty-potential">
      {data.map((pc) => (
        <div key={pc.label} className="bg-gray-50 dark:bg-gray-700 rounded p-3 text-center">
          <div className="text-2xl font-bold">{pc.count}</div>
          <div className="text-sm text-gray-600 dark:text-gray-200">{pc.label}</div>
        </div>
      ))}
    </div>
  );
}
