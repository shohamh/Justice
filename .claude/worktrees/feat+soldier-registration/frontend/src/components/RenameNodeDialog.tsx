import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { renameNode } from "../api/hierarchy";

interface Props {
  nodeId: string;
  currentName: string;
  onClose: () => void;
  onRenamed: () => void;
}

export default function RenameNodeDialog({ nodeId, currentName, onClose, onRenamed }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(currentName);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await renameNode(nodeId, name);
    onRenamed();
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="rename-dialog">
        <h3 className="font-semibold mb-4">{t("team.rename_node")}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <input className="border rounded p-1 w-full" value={name} onChange={(e) => setName(e.target.value)} required data-testid="rename-input" />
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1" onClick={onClose}>{t("team.cancel")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="rename-submit">{t("duty_config.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
