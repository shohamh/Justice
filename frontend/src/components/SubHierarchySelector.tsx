import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, fetchTree } from "../api/hierarchy";

interface Props {
  value: string[];
  onChange: (selected: string[]) => void;
}

function TreeNode({
  node,
  depth,
  value,
  onToggle,
}: {
  node: NodeDTO;
  depth: number;
  value: string[];
  onToggle: (id: string) => void;
}) {
  const hasChildren = !!node.children?.length;
  const [expanded, setExpanded] = useState(true);
  const checked = value.includes(node.id);

  return (
    <div>
      <div className="flex items-center gap-1 py-1 hover:bg-gray-50 dark:hover:bg-gray-700 rounded" style={{ paddingRight: `${depth * 16 + 4}px` }}>
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-[10px] shrink-0"
          aria-label={expanded ? "כווץ" : "הרחב"}
        >
          {hasChildren ? (expanded ? "▾" : "▸") : ""}
        </button>
        <label className="flex items-center gap-2 cursor-pointer flex-1 min-w-0">
          <input
            type="checkbox"
            checked={checked}
            onChange={() => onToggle(node.id)}
            className="rounded shrink-0"
          />
          <span className="text-sm truncate">{node.name}</span>
        </label>
      </div>
      {expanded && hasChildren && node.children!.map((child) => (
        <TreeNode key={child.id} node={child} depth={depth + 1} value={value} onToggle={onToggle} />
      ))}
    </div>
  );
}

export default function SubHierarchySelector({ value, onChange }: Props) {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const loadTree = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      setNodes(await fetchTree());
    } catch {
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { void loadTree(); }, [loadTree]);

  function toggleNode(nodeId: string) {
    if (value.includes(nodeId)) {
      onChange(value.filter((id) => id !== nodeId));
    } else {
      onChange([...value, nodeId]);
    }
  }

  return (
    <div className="border rounded p-2 max-h-60 overflow-y-auto dark:border-gray-600 dark:bg-gray-800" data-testid="sub-hierarchy-selector">
      <p className="text-xs text-gray-500 mb-2">{t("algorithm.select_eligible_nodes")}</p>
      {isLoading && <p role="status" className="text-xs text-gray-500">{t("team.hierarchy_loading")}</p>}
      {loadError && (
        <div role="alert" className="flex items-center gap-2 text-xs text-red-600 dark:text-red-400">
          <span>{t("team.hierarchy_load_failed")}</span>
          <button type="button" onClick={() => void loadTree()} className="underline">
            {t("team.hierarchy_retry")}
          </button>
        </div>
      )}
      {nodes.map((n) => (
        <TreeNode key={n.id} node={n} depth={0} value={value} onToggle={toggleNode} />
      ))}
    </div>
  );
}
