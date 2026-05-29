import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, updateNode } from "../api/hierarchy";
import { SoldierDTO, listSoldiers } from "../api/soldiers";

interface Props {
  node: NodeDTO;
  onClose: () => void;
  onAssigned: () => void;
}

export default function AssignCommanderDialog({ node, onClose, onAssigned }: Props) {
  const { t } = useTranslation();
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [selectedId, setSelectedId] = useState(node.commander_id ?? "");
  const [search, setSearch] = useState("");

  useEffect(() => {
    void (async () => {
      const all = await listSoldiers();
      setSoldiers(all);
    })();
  }, []);

  const filtered = soldiers.filter((s) =>
    s.full_name.includes(search) || s.personal_number.includes(search)
  );

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await updateNode(node.id, { commander_id: selectedId || null });
    onAssigned();
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="assign-commander-dialog">
        <h3 className="font-semibold mb-4">{t("team.assign_commander")}: {node.name}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <input className="border rounded p-1 w-full" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("my_requests.reason")} data-testid="commander-search" />
          <select className="border rounded p-1 w-full" value={selectedId} onChange={(e) => setSelectedId(e.target.value)} data-testid="commander-select">
            <option value="">—</option>
            {filtered.map((s) => (
              <option key={s.id} value={s.id}>{s.full_name} ({s.personal_number}) [{s.role}]</option>
            ))}
          </select>
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1" onClick={onClose}>{t("duty_config.delete")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="commander-submit">{t("approvals.approve")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
