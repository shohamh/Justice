import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { createNode } from "../api/hierarchy";
import { useLevelTypes } from "../hooks/useLevelTypes";
import Combobox, { type ComboboxItem } from "./Combobox";
import { translateApiError } from "../utils/translateApiError";

interface ParentNode {
  id: string;
  name: string;
  level?: string;
}

interface Props {
  onClose: () => void;
  onCreated: () => void;
  initialName?: string;
  /** If provided, shows a parent-unit picker in the dialog. */
  parentItems?: ComboboxItem[];
  /** Full node list used to look up the selected parent's level for rank filtering. */
  parentNodes?: ParentNode[];
}

export default function AddRootNodeDialog({ onClose, onCreated, initialName = "", parentItems, parentNodes }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(initialName);
  const { levelTypes } = useLevelTypes();
  const sortedTypes = [...levelTypes].sort((a, b) => a.rank - b.rank);
  const [level, setLevel] = useState("");
  const [parentId, setParentId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const rankByKey = useMemo(
    () => new Map(levelTypes.map((lt) => [lt.key, lt.rank])),
    [levelTypes],
  );

  const availableLevels = useMemo(() => {
    if (!parentId || !parentNodes) return sortedTypes;
    const parentNode = parentNodes.find((n) => n.id === parentId);
    if (!parentNode?.level) return sortedTypes;
    const parentRank = rankByKey.get(parentNode.level);
    if (parentRank === undefined) return sortedTypes;
    return sortedTypes.filter((lt) => lt.rank > parentRank);
  }, [parentId, parentNodes, sortedTypes, rankByKey]);

  useEffect(() => {
    if (availableLevels.length > 0) setLevel(availableLevels[0].key);
  }, [availableLevels]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createNode({ level, name, parent_id: parentId || null });
      onCreated();
      onClose();
    } catch (err: unknown) {
      setError(translateApiError(err, t, "שגיאה ביצירת היחידה"));
    }
  }

  if (levelTypes.length === 0) return null;

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="add-root-dialog">
        <h3 className="font-semibold mb-4 dark:text-gray-100">{t("team.add_root_node")}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          {parentItems && (
            <div>
              <label className="text-xs text-gray-500 dark:text-gray-400 block mb-0.5">תת-יחידה של (אופציונלי)</label>
              <Combobox
                items={parentItems}
                value={parentId}
                onChange={setParentId}
                placeholder="ללא הורה (שורש)"
              />
            </div>
          )}
          <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={level} onChange={(e) => setLevel(e.target.value)} data-testid="root-level">
            {availableLevels.map((lt) => (
              <option key={lt.key} value={lt.key}>{lt.label}</option>
            ))}
          </select>
          <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("team.node_name")} required data-testid="root-name" />
          {error && <p className="text-red-600 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1 dark:border-gray-600 dark:text-gray-300" onClick={onClose}>{t("team.cancel")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="root-submit">{t("team.add_node")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
