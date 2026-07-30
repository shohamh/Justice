import PopoverDropdown from "./PopoverDropdown";
import HierarchyNodeFilter from "./HierarchyNodeFilter";
import type { NodeDTO } from "../api/hierarchy";

interface Props {
  nodes: NodeDTO[];
  selected: string[];
  onChange: (ids: string[]) => void;
  triggerLabel: string;
}

export default function HierarchyTreeDropdown({ nodes, selected, onChange, triggerLabel }: Props) {
  return (
    <PopoverDropdown
      triggerLabel={triggerLabel}
      badgeCount={selected.length}
      panelClassName="absolute top-full mt-1 z-30 bg-white dark:bg-gray-800 border dark:border-gray-600 rounded-lg shadow-xl min-w-56 max-h-72 overflow-y-auto p-2"
    >
      {() => <HierarchyNodeFilter nodes={nodes} selected={selected} onChange={onChange} />}
    </PopoverDropdown>
  );
}
