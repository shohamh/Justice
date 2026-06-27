import { useState } from "react";
import { NodeDTO } from "../api/hierarchy";

interface Props {
  nodes: NodeDTO[];
  selected: string[];
  onChange: (ids: string[]) => void;
}

function FilterTreeNode({
  node,
  depth,
  selected,
  onToggle,
}: {
  node: NodeDTO;
  depth: number;
  selected: string[];
  onToggle: (id: string) => void;
}) {
  const hasChildren = !!node.children?.length;
  const [expanded, setExpanded] = useState(true);
  const checked = selected.includes(node.id);

  return (
    <div>
      <div
        className="flex items-center gap-1 py-0.5 hover:bg-gray-50 dark:hover:bg-gray-700 rounded"
        style={{ paddingRight: `${depth * 14 + 4}px` }}
      >
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-[10px] shrink-0"
          aria-label={expanded ? "כווץ" : "הרחב"}
        >
          {hasChildren ? (expanded ? "▾" : "▸") : ""}
        </button>
        <label className="flex items-center gap-1.5 cursor-pointer flex-1 min-w-0 text-xs text-gray-700 dark:text-gray-300">
          <input
            type="checkbox"
            checked={checked}
            onChange={() => onToggle(node.id)}
            className="accent-indigo-600 shrink-0"
          />
          <span className="truncate">{node.name}</span>
        </label>
      </div>
      {expanded && hasChildren && node.children!.map((child) => (
        <FilterTreeNode
          key={child.id}
          node={child}
          depth={depth + 1}
          selected={selected}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

export default function HierarchyNodeFilter({ nodes, selected, onChange }: Props) {
  function toggle(id: string) {
    if (selected.includes(id)) {
      onChange(selected.filter((s) => s !== id));
    } else {
      onChange([...selected, id]);
    }
  }

  return (
    <div className="p-2 max-h-64 overflow-y-auto">
      {selected.length > 0 && (
        <button
          type="button"
          onClick={() => onChange([])}
          className="mb-1 text-[10px] text-indigo-600 dark:text-indigo-400 hover:underline w-full text-right"
        >
          נקה סינון
        </button>
      )}
      {nodes.map((n) => (
        <FilterTreeNode key={n.id} node={n} depth={0} selected={selected} onToggle={toggle} />
      ))}
    </div>
  );
}
