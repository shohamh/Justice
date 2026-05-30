import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, deleteNode } from "../api/hierarchy";
import AddChildNodeDialog from "./AddChildNodeDialog";
import AssignCommanderDialog from "./AssignCommanderDialog";
import RenameNodeDialog from "./RenameNodeDialog";

const LEVEL_COLORS: Record<string, string> = {
  division: "text-purple-700 bg-purple-50",
  unit: "text-indigo-700 bg-indigo-50",
  department: "text-blue-700 bg-blue-50",
  branch: "text-green-700 bg-green-50",
  group: "text-yellow-700 bg-yellow-50",
  team: "text-gray-700 bg-gray-100",
};

interface Props {
  nodes: NodeDTO[];
  isAdmin: boolean;
  onChanged: () => void;
}

export default function HierarchyTree({ nodes, isAdmin, onChanged }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<string>>(new Set(nodes.filter((n) => n.path_ids.length <= 2).map((n) => n.id)));
  const [addDialog, setAddDialog] = useState<NodeDTO | null>(null);
  const [commanderDialog, setCommanderDialog] = useState<NodeDTO | null>(null);
  const [renameDialog, setRenameDialog] = useState<NodeDTO | null>(null);

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function handleDelete(id: string) {
    if (!confirm(t("team.remove") + "?")) return;
    try {
      await deleteNode(id);
      onChanged();
    } catch {
      alert(t("errors.generic"));
    }
  }

  const childrenOf = (parentId: string | null) =>
    nodes.filter((n) => n.parent_id === parentId).sort((a, b) => a.name.localeCompare(b.name));

  function renderNode(node: NodeDTO, depth: number) {
    const children = childrenOf(node.id);
    const isExpanded = expanded.has(node.id);
    const hasChildren = children.length > 0;

    const canHaveChildren = ["division", "unit", "department", "branch", "group"].includes(node.level);

    return (
      <li key={node.id} className="select-none">
        <div className={`flex items-center gap-2 py-1 px-2 hover:bg-gray-50 rounded ${depth > 0 ? "mr-4" : ""}`}>
          <button
            className={`w-4 h-4 flex items-center justify-center text-xs ${hasChildren ? "visible" : "invisible"}`}
            onClick={() => toggle(node.id)}
            data-testid={`tree-toggle-${node.id}`}
          >
            {isExpanded ? "▼" : "▶"}
          </button>
          <span className={`text-xs px-1.5 py-0.5 rounded ${LEVEL_COLORS[node.level] ?? ""}`}>
            {t(`team.level_${node.level}`)}
          </span>
          <span className="font-medium" data-testid={`tree-name-${node.id}`}>{node.name}</span>
          {node.commander_name && (
            <span className="text-xs text-gray-400" data-testid={`tree-commander-${node.id}`}>
              ({t("team.commander")}: {node.commander_name})
            </span>
          )}
          {isAdmin && (
            <span className="flex gap-1 ml-auto">
              {canHaveChildren && (
                <button className="text-xs text-indigo-600 hover:underline" onClick={() => setAddDialog(node)} data-testid={`tree-add-child-${node.id}`}>
                  +{t("team.add_node")}
                </button>
              )}
              <button className="text-xs text-green-600 hover:underline" onClick={() => setCommanderDialog(node)} data-testid={`tree-commander-btn-${node.id}`}>
                {t("exemptions.title")}
              </button>
              <button className="text-xs text-amber-600 hover:underline" onClick={() => setRenameDialog(node)} data-testid={`tree-rename-${node.id}`}>
                {t("duty_config.save")}
              </button>
              {!node.commander_id && children.length === 0 && (
                <button className="text-xs text-red-500 hover:underline" onClick={() => handleDelete(node.id)} data-testid={`tree-delete-${node.id}`}>
                  {t("duty_config.delete")}
                </button>
              )}
            </span>
          )}
        </div>
        {hasChildren && isExpanded && (
          <ul className="border-r-2 border-gray-100 mr-2">
            {children.map((child) => renderNode(child, depth + 1))}
          </ul>
        )}
      </li>
    );
  }

  const roots = childrenOf(null);

  return (
    <>
      <ul className="text-sm text-gray-700" data-testid="node-tree">
        {roots.map((node) => renderNode(node, 0))}
      </ul>

      {addDialog && (
        <AddChildNodeDialog parent={addDialog} onClose={() => setAddDialog(null)} onCreated={onChanged} />
      )}
      {commanderDialog && (
        <AssignCommanderDialog node={commanderDialog} onClose={() => setCommanderDialog(null)} onAssigned={onChanged} />
      )}
      {renameDialog && (
        <RenameNodeDialog nodeId={renameDialog.id} currentName={renameDialog.name} onClose={() => setRenameDialog(null)} onRenamed={onChanged} />
      )}
    </>
  );
}
