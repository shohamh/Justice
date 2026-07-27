import { useMemo, useState } from "react";

export interface HierarchyCheckboxTreeNode {
  id: string;
  name: string;
  level: string;
  parent_id: string | null;
}

interface Props {
  nodes: HierarchyCheckboxTreeNode[];
  selectedIds: Set<string>;
  onChange: (next: Set<string>) => void;
}

interface TreeNode extends HierarchyCheckboxTreeNode {
  children: TreeNode[];
}

function buildForest(nodes: HierarchyCheckboxTreeNode[]): TreeNode[] {
  const byId = new Map<string, TreeNode>(
    nodes.map((n) => [n.id, { ...n, children: [] }])
  );
  const roots: TreeNode[] = [];
  for (const node of byId.values()) {
    const parent = node.parent_id ? byId.get(node.parent_id) : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

function TreeRow({
  node,
  depth,
  selectedIds,
  onToggle,
}: {
  node: TreeNode;
  depth: number;
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
}) {
  const hasChildren = node.children.length > 0;
  const [expanded, setExpanded] = useState(depth === 0);
  const checked = selectedIds.has(node.id);

  return (
    <div>
      <div
        className="flex items-center gap-1 py-1 hover:bg-gray-50 dark:hover:bg-gray-700 rounded"
        style={{ paddingRight: `${depth * 16 + 4}px` }}
      >
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
      {expanded && hasChildren && node.children.map((child) => (
        <TreeRow key={child.id} node={child} depth={depth + 1} selectedIds={selectedIds} onToggle={onToggle} />
      ))}
    </div>
  );
}

export default function HierarchyCheckboxTree({ nodes, selectedIds, onChange }: Props) {
  const forest = useMemo(() => buildForest(nodes), [nodes]);

  function toggle(id: string) {
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    onChange(next);
  }

  return (
    <div className="border rounded p-2 max-h-60 overflow-y-auto dark:border-gray-600 dark:bg-gray-800" data-testid="hierarchy-checkbox-tree">
      {forest.map((n) => (
        <TreeRow key={n.id} node={n} depth={0} selectedIds={selectedIds} onToggle={toggle} />
      ))}
    </div>
  );
}
