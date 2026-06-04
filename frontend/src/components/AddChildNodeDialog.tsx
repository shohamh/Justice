import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, createNode } from "../api/hierarchy";

const LEVEL_ORDER = ["division", "unit", "department", "branch", "group", "team"];

interface Props {
  parent: NodeDTO;
  onClose: () => void;
  onCreated: () => void;
}

export default function AddChildNodeDialog({ parent, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState("");

  const parentIndex = LEVEL_ORDER.indexOf(parent.level);
  const possibleLevels = LEVEL_ORDER.slice(parentIndex + 1);
  const [level, setLevel] = useState(possibleLevels[0] ?? "");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await createNode({ level, name, parent_id: parent.id });
    onCreated();
    onClose();
  }

  if (possibleLevels.length === 0) return null;

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="add-child-dialog">
        <h3 className="font-semibold mb-4 dark:text-gray-100">{t("team.add_child_node")}: {parent.name}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={level} onChange={(e) => setLevel(e.target.value)} data-testid="child-level">
            {possibleLevels.map((l) => (
              <option key={l} value={l}>{t(`team.level_${l}`)}</option>
            ))}
          </select>
          <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("team.node_name")} required data-testid="child-name" />
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1 dark:border-gray-600 dark:text-gray-300" onClick={onClose}>{t("team.cancel")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="child-submit">{t("team.add_node")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
