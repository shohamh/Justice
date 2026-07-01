import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { createNode } from "../api/hierarchy";
import { useLevelTypes } from "../hooks/useLevelTypes";

interface Props {
  onClose: () => void;
  onCreated: () => void;
  initialName?: string;
}

export default function AddRootNodeDialog({ onClose, onCreated, initialName = "" }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(initialName);
  const { levelTypes } = useLevelTypes();
  const sortedTypes = [...levelTypes].sort((a, b) => a.rank - b.rank);
  const [level, setLevel] = useState("");

  useEffect(() => {
    if (!level && sortedTypes.length > 0) setLevel(sortedTypes[0].key);
  }, [sortedTypes, level]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await createNode({ level, name, parent_id: null });
    onCreated();
    onClose();
  }

  if (levelTypes.length === 0) return null;

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="add-root-dialog">
        <h3 className="font-semibold mb-4 dark:text-gray-100">{t("team.add_root_node")}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={level} onChange={(e) => setLevel(e.target.value)} data-testid="root-level">
            {sortedTypes.map((lt) => (
              <option key={lt.key} value={lt.key}>{lt.label}</option>
            ))}
          </select>
          <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("team.node_name")} required data-testid="root-name" />
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1 dark:border-gray-600 dark:text-gray-300" onClick={onClose}>{t("team.cancel")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="root-submit">{t("team.add_node")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
