import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import { SoldierDTO } from "../api/soldiers";
import { sortNodesByTree } from "../utils/sortNodesByTree";
import Combobox from "./Combobox";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  soldier: SoldierDTO;
  onSave: (data: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null }) => Promise<void>;
  onClose: () => void;
}

export default function SoldierEditModal({ soldier, onSave, onClose }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const [fullName, setFullName] = useState(soldier.full_name);
  const [phone, setPhone] = useState(soldier.phone ?? "");
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [hierarchyNodeId, setHierarchyNodeId] = useState(soldier.hierarchy_node_id ?? "");

  useEffect(() => {
    void (async () => {
      const all = await fetchTree();
      setNodes(all);
    })();
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const data: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null } = {};
    if (fullName !== soldier.full_name) data.full_name = fullName;
    if (phone !== (soldier.phone ?? "")) data.phone = phone || null;
    if (hierarchyNodeId !== (soldier.hierarchy_node_id ?? "")) data.hierarchy_node_id = hierarchyNodeId || null;
    await onSave(data);
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="soldier-edit-modal">
        <h3 className="font-semibold mb-4">{t("team.edit_soldier")}: {soldier.full_name}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <label className="block">
            <span className="text-xs">{t("team.full_name")}</span>
            <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={fullName} onChange={(e) => setFullName(e.target.value)} required data-testid="edit-soldier-name" />
          </label>
          <label className="block">
            <span className="text-xs">{t("profile.phone")}</span>
            <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={phone} onChange={(e) => setPhone(e.target.value)} data-testid="edit-soldier-phone" />
          </label>
          <label className="block">
            <span className="text-xs">{t("team.title")}</span>
            <Combobox
              items={sortNodesByTree(nodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
              value={hierarchyNodeId}
              onChange={setHierarchyNodeId}
              placeholder="—"
              testId="edit-soldier-node"
            />
          </label>
          <div className="flex justify-end gap-2">
            <button type="button" className="border dark:border-gray-600 dark:text-gray-300 rounded px-3 py-1" onClick={onClose}>{t("team.cancel")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="edit-soldier-submit">{t("duty_config.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
