import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { SoldierWithStatus } from "../api/commanderDashboard";
import { softDeleteSoldier } from "../api/soldiers";
import SoldierLink from "./SoldierLink";
import { grantExemption } from "../api/exemptions";
import { listExemptionTypes, type ExemptionType } from "../api/dutyConfig";
import { fetchTree, type NodeDTO } from "../api/hierarchy";
import { sortNodesByTree, indentedNodeLabel } from "../utils/sortNodesByTree";
import { updateSoldier } from "../api/soldiers";

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

  useEffect(() => {
    listExemptionTypes().then(setExemptionTypes).catch(() => {});
    fetchTree().then(setNodes).catch(() => {});
  }, []);

  async function handleRelease(soldierId: string) {
    if (!confirm(t("command_dashboard.confirm_release"))) return;
    await softDeleteSoldier(soldierId);
    onRefresh();
  }

  async function handleGrantExemption() {
    if (!exemptTarget || !exemptionTypeId || !exemptStart) return;
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
    await updateSoldier(moveTarget.id, { hierarchy_node_id: targetNodeId });
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
                <button onClick={() => setExemptTarget(s)} className="text-indigo-600 dark:text-indigo-400 text-xs">{t("command_dashboard.exempt")}</button>
                <button onClick={() => setMoveTarget(s)} className="text-indigo-600 dark:text-indigo-400 text-xs">{t("command_dashboard.move")}</button>
                <button onClick={() => handleRelease(s.id)} className="text-red-600 text-xs">{t("command_dashboard.release")}</button>
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
              <select className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={exemptionTypeId} onChange={(e) => setExemptionTypeId(e.target.value)}>
                <option value="">{t("command_dashboard.none")}</option>
                {exemptionTypes.map((et) => (
                  <option key={et.id} value={et.id}>{et.name}</option>
                ))}
              </select>
              <label className="block text-sm">{t("command_dashboard.exemption_start")}</label>
              <input type="date" className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={exemptStart} onChange={(e) => setExemptStart(e.target.value)} />
              <label className="block text-sm">{t("command_dashboard.exemption_end")}</label>
              <input type="date" className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={exemptEnd} onChange={(e) => setExemptEnd(e.target.value)} />
              <div className="flex gap-2 justify-end pt-2">
                <button onClick={() => setExemptTarget(null)} className="px-3 py-1 border rounded text-sm">{t("command_dashboard.cancel")}</button>
                <button onClick={handleGrantExemption} className="px-3 py-1 bg-indigo-600 text-white rounded text-sm">{t("command_dashboard.exempt")}</button>
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
              <select className="w-full border rounded p-2 text-gray-900 dark:text-white bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600" value={targetNodeId} onChange={(e) => setTargetNodeId(e.target.value)}>
                <option value="">{t("command_dashboard.none")}</option>
                {sortNodesByTree(nodes).map(({ node, depth }) => (
                  <option key={node.id} value={node.id}>{indentedNodeLabel(node, depth)}</option>
                ))}
              </select>
              <div className="flex gap-2 justify-end pt-2">
                <button onClick={() => setMoveTarget(null)} className="px-3 py-1 border rounded text-sm">{t("command_dashboard.cancel")}</button>
                <button onClick={handleMove} className="px-3 py-1 bg-indigo-600 text-white rounded text-sm">{t("command_dashboard.move_confirm")}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
