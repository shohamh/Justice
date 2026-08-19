import { useEffect, useMemo, useState } from "react";
import { NodeDTO, fetchFullTree } from "../api/hierarchy";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  onClose: () => void;
  onPicked: (nodeId: string, nodeName: string) => void;
}

interface FlatNode {
  id: string;
  name: string;
  level: string;
  parent_id: string | null;
}

interface TreeNode extends FlatNode {
  children: TreeNode[];
}

function flatten(nodes: NodeDTO[], parentId: string | null = null): FlatNode[] {
  const out: FlatNode[] = [];
  for (const n of nodes) {
    out.push({ id: n.id, name: n.name, level: n.level, parent_id: parentId });
    if (n.children && n.children.length > 0) {
      out.push(...flatten(n.children, n.id));
    }
  }
  return out;
}

function buildForest(nodes: FlatNode[]): TreeNode[] {
  const byId = new Map<string, TreeNode>(nodes.map((n) => [n.id, { ...n, children: [] }]));
  const roots: TreeNode[] = [];
  for (const node of byId.values()) {
    const parent = node.parent_id ? byId.get(node.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

function TreeRow({
  node, depth, onPicked,
}: {
  node: TreeNode;
  depth: number;
  onPicked: (id: string, name: string) => void;
}) {
  const hasChildren = node.children.length > 0;
  const [expanded, setExpanded] = useState(depth === 0);

  return (
    <div>
      <div
        className="flex items-center justify-between gap-1 py-1 hover:bg-gray-50 dark:hover:bg-gray-700 rounded"
        style={{ paddingRight: `${depth * 16 + 4}px` }}
      >
        <div className="flex items-center gap-1 min-w-0 flex-1">
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-[10px] shrink-0"
            aria-label={expanded ? "כווץ" : "הרחב"}
          >
            {hasChildren ? (expanded ? "▾" : "▸") : ""}
          </button>
          <span className="text-sm truncate dark:text-gray-100">{node.name}</span>
        </div>
        <button
          type="button"
          className="text-indigo-600 hover:underline text-xs shrink-0"
          onClick={() => onPicked(node.id, node.name)}
        >
          בחר
        </button>
      </div>
      {expanded && hasChildren && node.children.map((child) => (
        <TreeRow key={child.id} node={child} depth={depth + 1} onPicked={onPicked} />
      ))}
    </div>
  );
}

export default function HierarchyNodePickerModal({ onClose, onPicked }: Props) {
  useModalBackClose(onClose);
  const [nodes, setNodes] = useState<FlatNode[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchFullTree()
      .then((tree) => setNodes(flatten(tree)))
      .catch(() => setError("שגיאה בטעינת רשימת היחידות"))
      .finally(() => setLoading(false));
  }, []);

  const forest = useMemo(() => buildForest(nodes), [nodes]);

  const filtered = useMemo(() => {
    const q = search.trim();
    if (!q) return null;
    return nodes.filter((n) => n.name.includes(q));
  }, [nodes, search]);

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96 max-h-[80dvh] flex flex-col"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-semibold dark:text-gray-100">בחר יחידה</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        <input
          className="border rounded p-1.5 w-full mb-3 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 text-sm"
          placeholder="חיפוש..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        {error && <p className="text-red-500 text-xs mb-2">{error}</p>}
        {loading && <p className="text-gray-400 text-xs mb-2">טוען...</p>}

        <div className="overflow-y-auto flex-1 space-y-1">
          {filtered === null ? (
            forest.map((n) => <TreeRow key={n.id} node={n} depth={0} onPicked={onPicked} />)
          ) : (
            filtered.map((n) => (
              <div
                key={n.id}
                className="flex items-center justify-between text-sm p-1.5 rounded hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <span className="dark:text-gray-100">{n.name}</span>
                <button
                  type="button"
                  className="text-indigo-600 hover:underline text-xs"
                  onClick={() => onPicked(n.id, n.name)}
                >
                  בחר
                </button>
              </div>
            ))
          )}
          {!loading && filtered !== null && filtered.length === 0 && (
            <p className="text-gray-400 text-xs text-center py-4">לא נמצאו יחידות</p>
          )}
        </div>
      </div>
    </div>
  );
}
