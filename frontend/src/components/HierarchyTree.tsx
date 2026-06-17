import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, deleteNode } from "../api/hierarchy";
import { SoldierDTO, updateSoldier, onboardSoldier } from "../api/soldiers";
import AddChildNodeDialog from "./AddChildNodeDialog";
import AssignCommanderDialog from "./AssignCommanderDialog";
import RenameNodeDialog from "./RenameNodeDialog";
import SoldierSearchAutocomplete from "./SoldierSearchAutocomplete";
import UnifiedSoldierModal from "./UnifiedSoldierModal";
import SoldierLink from "./SoldierLink";
import TelegramBadge from "./TelegramBadge";

function SoldierAvatar({ url, name }: { url?: string | null; name: string }) {
  const initials = name.split(" ").map((w) => w[0]).filter(Boolean).slice(0, 2).join("");
  if (url) {
    return <img src={url} alt={name} className="w-5 h-5 rounded-full object-cover border border-gray-200 dark:border-gray-600 shrink-0" onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />;
  }
  return <span className="w-5 h-5 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center text-indigo-700 dark:text-indigo-300 font-semibold text-[9px] shrink-0">{initials}</span>;
}

const LEVEL_COLORS: Record<string, string> = {
  division: "text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-950",
  unit: "text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-950",
  department: "text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950",
  branch: "text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-950",
  group: "text-yellow-700 dark:text-yellow-300 bg-yellow-50 dark:bg-yellow-950",
  team: "text-gray-700 bg-gray-100 dark:text-gray-300 dark:bg-gray-700",
};

const LEVEL_ORDER = ["division", "unit", "department", "branch", "group", "team"];

interface Props {
  nodes: NodeDTO[];
  soldiers: SoldierDTO[];
  isAdmin: boolean;
  onChanged: () => void;
  user: { role: string; id: string } | null;
}

export default function HierarchyTree({ nodes, soldiers, isAdmin, onChanged }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<string>>(new Set(nodes.filter((n) => n.path_ids.length <= 2).map((n) => n.id)));
  const [addDialog, setAddDialog] = useState<NodeDTO | null>(null);
  const [commanderDialog, setCommanderDialog] = useState<NodeDTO | null>(null);
  const [renameDialog, setRenameDialog] = useState<NodeDTO | null>(null);
  const [quickAddNode, setQuickAddNode] = useState<string | null>(null);
  const [editSoldier, setEditSoldier] = useState<SoldierDTO | null>(null);

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

  async function handleQuickAdd(nodeId: string, soldier: SoldierDTO | null, personalNumber: string, fullName: string) {
    try {
      if (soldier) {
        await updateSoldier(soldier.id, { hierarchy_node_id: nodeId });
      } else {
        await onboardSoldier({ personal_number: personalNumber, full_name: fullName, hierarchy_node_id: nodeId });
      }
      setQuickAddNode(null);
      setExpanded((prev) => new Set(prev).add(nodeId));
      onChanged();
    } catch {
      alert(t("errors.generic"));
    }
  }

  const childrenOf = (parentId: string | null) =>
    nodes.filter((n) => n.parent_id === parentId).sort((a, b) => a.name.localeCompare(b.name));

  const soldiersOf = (nodeId: string) => {
    // Soldiers whose hierarchy_node_id points here, excluding those who are
    // commanders of a different node (they appear under their commanded node)
    const assigned = soldiers.filter((s) => {
      if (s.hierarchy_node_id !== nodeId) return false;
      if (s.left_at) return false;
      const isCommanderElsewhere = nodes.some((n) => n.commander_id === s.id && n.id !== nodeId);
      return !isCommanderElsewhere;
    });
    // If this node has a commander not already in the list, add them
    const node = nodes.find((n) => n.id === nodeId);
    if (node?.commander_id) {
      const cmdr = soldiers.find((s) => s.id === node.commander_id && !s.left_at);
      if (cmdr && !assigned.some((s) => s.id === cmdr.id)) {
        return [...assigned, cmdr];
      }
    }
    return assigned;
  };

  const canHaveChildren = (level: string) => {
    const idx = LEVEL_ORDER.indexOf(level);
    return idx >= 0 && idx < LEVEL_ORDER.length - 1;
  };

  function renderNode(node: NodeDTO, depth: number) {
    const children = childrenOf(node.id);
    const isExpanded = expanded.has(node.id);
    const hasChildren = children.length > 0;
    const nodeSoldiers = soldiersOf(node.id);

    return (
      <li key={node.id} className="select-none">
        <div className={`flex items-center gap-2 py-1 px-2 hover:bg-gray-50 dark:hover:bg-gray-700 rounded ${depth > 0 ? "mr-4" : ""}`}>
          <button
            className={`w-4 h-4 flex items-center justify-center text-xs ${hasChildren || nodeSoldiers.length > 0 ? "visible" : "invisible"}`}
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
              {canHaveChildren(node.level) && (
                <button className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline" onClick={() => setAddDialog(node)} data-testid={`tree-add-child-${node.id}`}>
                  +{t("team.add_node")}
                </button>
              )}
              <button className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline" onClick={() => setQuickAddNode(node.id)} data-testid={`tree-add-soldier-${node.id}`}>
                +{t("team.add_soldier")}
              </button>
              <button className="text-xs text-green-600 hover:underline" onClick={() => setCommanderDialog(node)} data-testid={`tree-commander-btn-${node.id}`}>
                {t("team.assign_commander")}
              </button>
              <button className="text-xs text-amber-600 hover:underline" onClick={() => setRenameDialog(node)} data-testid={`tree-rename-${node.id}`}>
                {t("team.edit")}
              </button>
              {!node.commander_id && children.length === 0 && (
                <button className="text-xs text-red-500 hover:underline" onClick={() => handleDelete(node.id)} data-testid={`tree-delete-${node.id}`}>
                  {t("duty_config.delete")}
                </button>
              )}
            </span>
          )}
        </div>

        {quickAddNode === node.id && (
          <div className="mr-8 mb-2 px-2" data-testid={`quick-add-${node.id}`}>
            <SoldierSearchAutocomplete
              onSelect={(s) => {
                if (s) {
                  void handleQuickAdd(node.id, s, "", "");
                }
              }}
              onCreateNew={(pn, name) => {
                void handleQuickAdd(node.id, null, pn || "", name || "");
              }}
            />
          </div>
        )}

        {isExpanded && nodeSoldiers.length > 0 && (
          <ul className="mr-8 mb-1" data-testid={`tree-soldiers-${node.id}`}>
            {nodeSoldiers.map((s) => (
              <li key={s.id} className="flex items-center gap-2 py-0.5 px-2 text-sm text-gray-700 dark:text-gray-200" data-testid={`tree-soldier-${s.personal_number}`}>
                <SoldierAvatar url={s.profile_picture_url} name={s.full_name} />
                <SoldierLink id={s.id} name={s.full_name} />
                <span className="text-xs text-gray-400">({s.personal_number})</span>
                <TelegramBadge linked={s.telegram_linked} />
                {isAdmin && (
                  <button
                    className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline ml-auto"
                    onClick={() => setEditSoldier(s)}
                    data-testid={`edit-soldier-${s.personal_number}`}
                  >
                    {t("team.edit")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

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
      <ul className="text-sm text-gray-900 dark:text-white" data-testid="node-tree">
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
      {editSoldier && (
        <UnifiedSoldierModal
          soldier={editSoldier}
          score={null}
          nodes={nodes}
          onClose={() => setEditSoldier(null)}
          onRefresh={onChanged}
        />
      )}
    </>
  );
}
