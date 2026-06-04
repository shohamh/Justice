import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, fetchTree } from "../api/hierarchy";

interface Props {
  value: string[];
  onChange: (selected: string[]) => void;
}

export default function SubHierarchySelector({ value, onChange }: Props) {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);

  useEffect(() => { void fetchTree().then(setNodes); }, []);

  function toggleNode(nodeId: string) {
    if (value.includes(nodeId)) {
      onChange(value.filter((id) => id !== nodeId));
    } else {
      onChange([...value, nodeId]);
    }
  }

  function renderNode(node: NodeDTO, depth = 0): React.ReactNode {
    const checked = value.includes(node.id);
    return (
      <div key={node.id}>
        <label className="flex items-center gap-2 py-1 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer" style={{ paddingRight: `${depth * 16 + 8}px` }}>
          <input type="checkbox" checked={checked} onChange={() => toggleNode(node.id)} className="rounded" />
          <span className="text-sm">{node.name}</span>
        </label>
        {node.children?.map((child) => renderNode(child, depth + 1))}
      </div>
    );
  }

  return (
    <div className="border rounded p-2 max-h-60 overflow-y-auto dark:border-gray-600 dark:bg-gray-800" data-testid="sub-hierarchy-selector">
      <p className="text-xs text-gray-500 mb-2">{t("algorithm.select_eligible_nodes")}</p>
      {nodes.map((n) => renderNode(n))}
    </div>
  );
}
