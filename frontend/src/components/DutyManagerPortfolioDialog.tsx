import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO } from "../api/hierarchy";
import { assignDmScope, DmScopeEntry, listDmScope, removeDmScope } from "../api/dmScope";
import Combobox from "./Combobox";
import { sortNodesByTree } from "../utils/sortNodesByTree";
import { useModalBackClose } from "../hooks/useModalBackClose";
import MessageDialog from "./MessageDialog";

interface Props {
  soldierId: string;
  soldierName: string;
  nodes: NodeDTO[];
  onClose: () => void;
  onChanged: () => void;
}

export default function DutyManagerPortfolioDialog({ soldierId, soldierName, nodes, onClose, onChanged }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const [entries, setEntries] = useState<DmScopeEntry[]>([]);
  const [addNodeId, setAddNodeId] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setEntries(await listDmScope(soldierId));
  }, [soldierId]);
  useEffect(() => { void refresh(); }, [refresh]);

  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  // Sort the FULL tree first so depth/indentation reflects real hierarchy, then
  // hide rows the viewer can't manage — filtering before sorting would orphan a
  // manageable subtree whose own parent isn't manageable.
  const assignedNodeIds = new Set(entries.map((e) => e.hierarchy_node_id));
  const manageableSorted = sortNodesByTree(nodes).filter(
    ({ node }) => node.dm_manageable && !assignedNodeIds.has(node.id)
  );

  async function handleAdd() {
    if (!addNodeId) return;
    setLoading(true);
    try {
      await assignDmScope(soldierId, addNodeId);
      setAddNodeId("");
      await refresh();
      onChanged();
    } catch {
      setMessage(t("errors.generic", "שגיאה"));
    } finally {
      setLoading(false);
    }
  }

  async function handleRemove(entryId: string) {
    try {
      await removeDmScope(entryId);
      await refresh();
      onChanged();
    } catch {
      setMessage(t("errors.generic", "שגיאה"));
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96"
        onClick={(e) => e.stopPropagation()}
        data-testid="duty-manager-portfolio-dialog"
      >
        <h3 className="font-semibold mb-4 dark:text-gray-100">
          {t("team.duty_manager_portfolio")}: {soldierName}
        </h3>

        {entries.length === 0 ? (
          <p className="text-sm text-gray-500 mb-3">{t("team.no_duty_manager_scopes")}</p>
        ) : (
          <ul className="space-y-1 mb-3" data-testid="portfolio-list">
            {entries.map((e) => (
              <li
                key={e.id}
                className="flex items-center justify-between text-sm border-b dark:border-gray-600 py-1"
              >
                <span>{nodeById.get(e.hierarchy_node_id)?.name ?? e.hierarchy_node_id}</span>
                <button
                  type="button"
                  className="text-red-500 hover:text-red-700 text-xs"
                  onClick={() => void handleRemove(e.id)}
                  data-testid={`remove-portfolio-${e.id}`}
                >
                  {t("notifications.remove")}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex gap-2 items-end pt-2 border-t dark:border-gray-600">
          <div className="flex-1">
            <Combobox
              items={manageableSorted.map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
              value={addNodeId}
              onChange={setAddNodeId}
              placeholder="—"
              testId="portfolio-add-node"
            />
          </div>
          <button
            type="button"
            className="bg-indigo-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
            disabled={!addNodeId || loading}
            onClick={() => void handleAdd()}
            data-testid="portfolio-add-submit"
          >
            {t("team.add")}
          </button>
        </div>

        <div className="flex justify-end mt-4">
          <button
            type="button"
            className="border rounded px-3 py-1 dark:text-gray-100 dark:border-gray-600"
            onClick={onClose}
          >
            {t("app.close")}
          </button>
        </div>
      </div>
      <MessageDialog open={message !== null} title={t("common.error", "שגיאה")} message={message ?? ""} onClose={() => setMessage(null)} />
    </div>
  );
}
