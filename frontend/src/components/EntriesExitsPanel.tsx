import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { SoldierWithStatus } from "../api/commanderDashboard";
import { softDeleteSoldier } from "../api/soldiers";
import SoldierLink from "./SoldierLink";
import { grantExemption } from "../api/exemptions";
import { listExemptionTypes, type ExemptionType } from "../api/dutyConfig";
import { fetchTree, type NodeDTO } from "../api/hierarchy";
import { sortNodesByTree } from "../utils/sortNodesByTree";
import { createTransferRequest } from "../api/hierarchyTransfers";
import Combobox from "./Combobox";
import DateInput from "../components/DateInput";
import { isDateRangeValid } from "../utils/formatDate";

interface Props {
  soldiers: SoldierWithStatus[];
  onRefresh: () => void;
}

export default function EntriesExitsPanel({ soldiers, onRefresh }: Props) {
  const { t } = useTranslation();
  const [exemptionTypes, setExemptionTypes] = useState<ExemptionType[]>([]);
  const [nodes, setNodes] = useState<NodeDTO[]>([]);

  const [exemptTarget, setExemptTarget] = useState<SoldierWithStatus | null>(null);
  const [exemptionTypeId, setExemptionTypeId] = useState("");
  const [exemptStart, setExemptStart] = useState("");
  const [exemptEnd, setExemptEnd] = useState("");

  const [moveTarget, setMoveTarget] = useState<SoldierWithStatus | null>(null);
  const [targetNodeId, setTargetNodeId] = useState("");

  const [releaseTarget, setReleaseTarget] = useState<SoldierWithStatus | null>(null);
  const [releaseDate, setReleaseDate] = useState("");

  useEffect(() => {
    listExemptionTypes().then(setExemptionTypes).catch(() => {});
    fetchTree().then(setNodes).catch(() => {});
  }, []);

  function openReleaseModal(s: SoldierWithStatus) {
    setReleaseTarget(s);
    setReleaseDate(new Date().toISOString().slice(0, 10));
  }

  async function handleConfirmRelease() {
    if (!releaseTarget) return;
    await softDeleteSoldier(releaseTarget.id, releaseDate);
    setReleaseTarget(null);
    onRefresh();
  }

  async function handleGrantExemption() {
    if (!exemptTarget || !exemptionTypeId || !exemptStart || !isDateRangeValid(exemptStart, exemptEnd)) return;
    await grantExemption(exemptTarget.id, {
      exemption_type_id: exemptionTypeId,
      start_date: exemptStart,
      end_date: exemptEnd || null,
    });
    setExemptTarget(null);
    setExemptionTypeId("");
    setExemptStart("");
    setExemptEnd("");
    onRefresh();
  }

  async function handleMove() {
    if (!moveTarget || !targetNodeId) return;
    await createTransferRequest(moveTarget.id, targetNodeId);
    setMoveTarget(null);
    setTargetNodeId("");
    onRefresh();
  }

  return (
    <div className="overflow-x-auto" data-testid="entries-exits-panel">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b dark:border-gray-700">
            <th className="text-right p-1">{t("command_dashboard.name")}</th>
            <th className="text-right p-1">{t("command_dashboard.status")}</th>
            <th className="text-right p-1">{t("command_dashboard.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {soldiers.map((s) => (
            <tr key={s.id} className="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700">
              <td className="p-1"><SoldierLink id={s.id} name={s.full_name} /></td>
              <td className="p-1">{s.status}</td>
              <td className="p-1 space-x-2 space-x-reverse">
                <button onClick={() => setExemptTarget(s)} className="text-indigo-600 dark:text-indigo-300 text-xs">{t("command_dashboard.exempt")}</button>
                <button onClick={() => setMoveTarget(s)} className="text-indigo-600 dark:text-indigo-300 text-xs">{t("command_dashboard.move")}</button>
                <button onClick={() => openReleaseModal(s)} className="text-red-600 text-xs">{t("command_dashboard.release")}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {exemptTarget && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setExemptTarget(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-bold text-lg mb-4">{t("command_dashboard.grant_exemption")} - {exemptTarget.full_name}</h3>
            <div className="space-y-3">
              <label className="block text-sm">{t("command_dashboard.exemption_type")}</label>
              <Combobox
                items={exemptionTypes.map(et => ({ id: et.id, name: et.name }))}
                value={exemptionTypeId}
                onChange={setExemptionTypeId}
                placeholder={t("command_dashboard.none")}
              />
              <label className="block text-sm">{t("command_dashboard.exemption_start")}</label>
              <DateInput className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={exemptStart} onChange={(v) => setExemptStart(v)} max={exemptEnd || undefined} />
              <label className="block text-sm">{t("command_dashboard.exemption_end")}</label>
              <DateInput className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={exemptEnd} onChange={(v) => setExemptEnd(v)} min={exemptStart || undefined} />
              <div className="flex gap-2 justify-end pt-2">
                <button onClick={() => setExemptTarget(null)} className="px-3 py-1 border rounded text-sm">{t("command_dashboard.cancel")}</button>
                <button onClick={handleGrantExemption} disabled={!isDateRangeValid(exemptStart, exemptEnd)} className="px-3 py-1 bg-indigo-600 text-white rounded text-sm disabled:opacity-50">{t("command_dashboard.exempt")}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {moveTarget && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setMoveTarget(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-bold text-lg mb-4">{t("command_dashboard.move_soldier")} - {moveTarget.full_name}</h3>
            <div className="space-y-3">
              <label className="block text-sm">{t("command_dashboard.target_node")}</label>
              <Combobox
                items={sortNodesByTree(nodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
                value={targetNodeId}
                onChange={setTargetNodeId}
                placeholder={t("command_dashboard.none")}
              />
              <div className="flex gap-2 justify-end pt-2">
                <button onClick={() => setMoveTarget(null)} className="px-3 py-1 border rounded text-sm">{t("command_dashboard.cancel")}</button>
                <button onClick={handleMove} className="px-3 py-1 bg-indigo-600 text-white rounded text-sm">{t("command_dashboard.move_confirm")}</button>
              </div>
            </div>
          </div>
        </div>
      )}
      {releaseTarget && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setReleaseTarget(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-bold text-lg mb-4">{t("command_dashboard.release")} - {releaseTarget.full_name}</h3>
            <div className="space-y-3">
              <label className="block text-sm">{t("command_dashboard.release_date")}</label>
              <DateInput data-testid="release-date-input" className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                value={releaseDate} onChange={(v) => setReleaseDate(v)} autoFocus />
              <div className="flex gap-2 justify-end pt-2">
                <button onClick={() => setReleaseTarget(null)} className="px-3 py-1 border rounded text-sm">{t("command_dashboard.cancel")}</button>
                <button onClick={handleConfirmRelease} className="px-3 py-1 bg-red-600 text-white rounded text-sm">{t("command_dashboard.confirm_release")}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
