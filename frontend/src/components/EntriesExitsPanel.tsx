import { useTranslation } from "react-i18next";
import type { SoldierWithStatus } from "../api/commanderDashboard";
import { softDeleteSoldier } from "../api/soldiers";

interface Props {
  soldiers: SoldierWithStatus[];
  onRefresh: () => void;
}

export default function EntriesExitsPanel({ soldiers, onRefresh }: Props) {
  const { t } = useTranslation();

  async function handleRelease(soldierId: string) {
    if (!confirm(t("command_dashboard.confirm_release"))) return;
    await softDeleteSoldier(soldierId);
    onRefresh();
  }

  return (
    <div className="overflow-x-auto" data-testid="entries-exits-panel">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="text-right p-1">{t("command_dashboard.name")}</th>
            <th className="text-right p-1">{t("command_dashboard.status")}</th>
            <th className="text-right p-1">{t("command_dashboard.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {soldiers.map((s) => (
            <tr key={s.id} className="border-b hover:bg-gray-50">
              <td className="p-1">{s.full_name}</td>
              <td className="p-1">{s.status}</td>
              <td className="p-1 space-x-2 space-x-reverse">
                <button className="text-indigo-600 text-xs">{t("command_dashboard.exempt")}</button>
                <button className="text-indigo-600 text-xs">{t("command_dashboard.move")}</button>
                <button onClick={() => handleRelease(s.id)} className="text-red-600 text-xs">{t("command_dashboard.release")}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
