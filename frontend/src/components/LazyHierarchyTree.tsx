import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { EllipsisVertical } from "lucide-react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  DragEndEvent,
  DragOverlay,
  PointerSensor,
  useDroppable,
  useDraggable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";

import { queryKeys } from "../queryKeys";
import {
  fetchHierarchyBranchPage,
  isStaleHierarchyCursorError,
  NodeDTO,
  searchHierarchyNodes,
  deleteNode,
  moveNode,
} from "../api/hierarchy";
import {
  isStaleSoldierRosterCursorError,
  listSoldierRosterPage,
  onboardSoldier,
  SoldierRosterItemDTO,
  SoldierRosterSort,
} from "../api/soldiers";
import { createTransferRequest } from "../api/hierarchyTransfers";
import { useSoldierModal } from "../contexts/SoldierModalContext";
import { type ColDef } from "./DataTable";
import CursorPagedTable from "./CursorPagedTable";
import PopoverDropdown from "./PopoverDropdown";
import AddChildNodeDialog from "./AddChildNodeDialog";
import AssignCommanderDialog from "./AssignCommanderDialog";
import AssignDutyManagersDialog from "./AssignDutyManagersDialog";
import EditNodeDialog from "./EditNodeDialog";
import ConfirmDialog from "./ConfirmDialog";
import MessageDialog from "./MessageDialog";
import SoldierSearchAutocomplete from "./SoldierSearchAutocomplete";
import SoldierLink from "./SoldierLink";
import TelegramBadge from "./TelegramBadge";
import { useLevelTypes } from "../hooks/useLevelTypes";
import { translateApiError } from "../utils/translateApiError";

interface DragDataSoldier {
  kind: "soldier";
  id: string;
  name: string;
  fromNodeId: string;
  isCommander: boolean;
}

interface DragDataNode {
  kind: "node";
  id: string;
  name: string;
}

type DragData = DragDataSoldier | DragDataNode;

interface PendingTransfer {
  soldierId: string;
  soldierName: string;
  nodeId: string;
  nodeName: string;
  nodeLevel: string;
}

interface TransferSuccessInfo {
  commander: { id: string; name: string } | null;
}

interface Props {
  scopeKey: string;
  roleOrder: string[];
  canManageLevelTypes: boolean;
  onChanged: () => void | Promise<void>;
  onSelectedNodeChange: (node: NodeDTO | null) => void;
  onOpenPortfolio: (soldierId: string, soldierName: string) => void;
}

function SoldierDragHandle({
  soldier,
  nodeId,
}: {
  soldier: SoldierRosterItemDTO;
  nodeId: string;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `soldier:${soldier.id}`,
    data: {
      kind: "soldier",
      id: soldier.id,
      name: soldier.full_name,
      fromNodeId: nodeId,
      isCommander: soldier.is_commander,
    } satisfies DragDataSoldier,
  });
  return (
    <button
      ref={setNodeRef}
      type="button"
      {...attributes}
      {...listeners}
      className={`cursor-grab touch-none p-1 text-gray-400 hover:text-gray-600 active:cursor-grabbing ${isDragging ? "opacity-40" : ""}`}
      aria-label={soldier.full_name}
      title={soldier.full_name}
    >
      ⠿
    </button>
  );
}

function BranchTail({
  hasMore,
  busy,
  failed,
  onLoadMore,
  labels,
}: {
  hasMore: boolean;
  busy: boolean;
  failed: boolean;
  onLoadMore: () => void;
  labels: { loading: string; loadMore: string; retry: string };
}) {
  const tailRef = useRef<HTMLLIElement>(null);
  useEffect(() => {
    const tail = tailRef.current;
    if (!tail || !hasMore || busy || failed || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onLoadMore();
      },
      { rootMargin: "240px" },
    );
    observer.observe(tail);
    return () => observer.disconnect();
  }, [busy, failed, hasMore, onLoadMore]);

  if (!hasMore && !failed) return null;
  return (
    <li ref={tailRef} className="py-1 text-center">
      <button type="button" onClick={onLoadMore} disabled={busy} className="text-sm text-indigo-600 dark:text-indigo-300 disabled:opacity-60">
        {failed ? labels.retry : busy ? labels.loading : labels.loadMore}
      </button>
    </li>
  );
}

function NodeSoldiers({
  nodeId,
  scopeKey,
  onOpenSoldier,
  t,
}: {
  nodeId: string;
  scopeKey: string;
  onOpenSoldier: (soldierId: string) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const queryClient = useQueryClient();
  // Nested under the branch keys so the tree's existing resets also refresh these.
  const queryKey = useMemo(() => [...queryKeys.hierarchyBranches(scopeKey), "soldiers", nodeId] as const, [scopeKey, nodeId]);
  const soldiersQuery = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) =>
      listSoldierRosterPage({
        cursor: pageParam,
        node_id: nodeId,
        direct_node_only: true,
        active_only: true,
        search: "",
        sort: "full_name",
        descending: false,
        page_size: 50,
        signal,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: Infinity,
    gcTime: 5 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const soldiers = useMemo(() => soldiersQuery.data?.pages.flatMap((page) => page.items) ?? [], [soldiersQuery.data]);
  const loadMore = useCallback(() => {
    if (soldiersQuery.isFetchNextPageError && isStaleSoldierRosterCursorError(soldiersQuery.error)) {
      void queryClient.resetQueries({ queryKey, exact: true });
    } else if (soldiersQuery.hasNextPage) {
      void soldiersQuery.fetchNextPage();
    } else if (soldiersQuery.isError) {
      void soldiersQuery.refetch();
    }
  }, [queryClient, queryKey, soldiersQuery]);

  return (
    <>
      {soldiersQuery.isPending && <li className="mr-4 py-1 text-sm text-gray-500" role="status">{t("team.roster_loading")}</li>}
      {soldiersQuery.isError && soldiers.length === 0 && (
        <li className="mr-4 py-1 text-sm text-red-600" role="alert">
          {t("team.roster_load_failed")} <button type="button" className="underline" onClick={loadMore}>{t("team.roster_retry")}</button>
        </li>
      )}
      {soldiers.map((soldier) => (
        <li key={soldier.id} className="flex items-center gap-2 px-2 py-1 mr-4 rounded hover:bg-gray-50 dark:hover:bg-gray-700" data-testid={`tree-soldier-${soldier.personal_number}`}>
          <SoldierDragHandle soldier={soldier} nodeId={nodeId} />
          <button type="button" className="min-w-0 truncate text-right text-indigo-600 dark:text-indigo-300 hover:underline" onClick={() => onOpenSoldier(soldier.id)}>
            {soldier.full_name}
          </button>
          <span className="shrink-0 text-xs text-gray-500 dark:text-gray-400">{t(`role.${soldier.role}`)}</span>
        </li>
      ))}
      <BranchTail
        hasMore={Boolean(soldiersQuery.hasNextPage)}
        busy={soldiersQuery.isFetchingNextPage}
        failed={soldiersQuery.isFetchNextPageError}
        onLoadMore={loadMore}
        labels={{ loading: t("team.roster_loading_more"), loadMore: t("team.roster_load_more"), retry: t("team.roster_retry") }}
      />
    </>
  );
}

function SearchPathTreeItem({
  path,
  index,
  selectedNodeId,
  onSelect,
}: {
  path: NodeDTO[];
  index: number;
  selectedNodeId: string | null;
  onSelect: (node: NodeDTO) => void;
}) {
  const node = path[index];
  const hasPathChild = index < path.length - 1;
  return (
    <li role="treeitem" aria-level={index + 1} aria-expanded={hasPathChild ? true : undefined}>
      <div className={`flex items-center gap-2 rounded px-2 py-1 ${selectedNodeId === node.id ? "bg-indigo-100 dark:bg-indigo-900/50" : ""}`}>
        <span aria-hidden="true" className="w-4 text-center text-xs text-indigo-500">
          {hasPathChild ? "▼" : "•"}
        </span>
        <button
          type="button"
          className="min-w-0 truncate text-right font-medium hover:underline"
          aria-current={selectedNodeId === node.id ? "location" : undefined}
          onClick={() => onSelect(node)}
        >
          {node.name}
        </button>
      </div>
      {hasPathChild && (
        <ul role="group" className="mr-4 border-r-2 border-indigo-200 dark:border-indigo-800">
          <SearchPathTreeItem
            path={path}
            index={index + 1}
            selectedNodeId={selectedNodeId}
            onSelect={onSelect}
          />
        </ul>
      )}
    </li>
  );
}

function TreeNodeBranch({
  node,
  depth,
  scopeKey,
  expanded,
  selectedNodeId,
  knownNodes,
  levelTypesLoading,
  labelByKey,
  maxRank,
  rankByKey,
  onToggle,
  onBranchData,
  onAddChild,
  onAddSoldier,
  onAssignCommander,
  onManageDutyManagers,
  onOpenPortfolio,
  onOpenSoldier,
  onRename,
  onDelete,
  onSelect,
  onMessage,
  t,
}: {
  node: NodeDTO;
  depth: number;
  scopeKey: string;
  expanded: Set<string>;
  selectedNodeId: string | null;
  knownNodes: NodeDTO[];
  levelTypesLoading: boolean;
  labelByKey: Map<string, string>;
  maxRank: number;
  rankByKey: Map<string, number>;
  onToggle: (node: NodeDTO) => void;
  onBranchData: (parentId: string | null, nodes: NodeDTO[]) => void;
  onAddChild: (node: NodeDTO) => void;
  onAddSoldier: (nodeId: string) => void;
  onAssignCommander: (node: NodeDTO) => void;
  onManageDutyManagers: (nodeId: string) => void;
  onOpenPortfolio: (soldierId: string, soldierName: string) => void;
  onOpenSoldier: (soldierId: string) => void;
  onRename: (node: NodeDTO) => void;
  onDelete: (nodeId: string) => void;
  onSelect: (node: NodeDTO) => void;
  onMessage: (message: string) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const queryClient = useQueryClient();
  const { setNodeRef: setDropNodeRef, isOver } = useDroppable({
    id: `node-drop:${node.id}`,
    data: { kind: "node-drop-target", nodeId: node.id },
  });
  const isExpanded = expanded.has(node.id);
  const canExpand = node.has_children === true || node.has_soldiers === true;
  const queryKey = queryKeys.hierarchyBranch(scopeKey, node.id);
  const childrenQuery = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) =>
      fetchHierarchyBranchPage({ parentId: node.id, cursor: pageParam, signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    enabled: isExpanded && node.has_children === true,
    staleTime: Infinity,
    gcTime: 5 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const children = useMemo(
    () => childrenQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [childrenQuery.data],
  );
  useEffect(() => onBranchData(node.id, children), [children, node.id, onBranchData]);
  const loadMore = useCallback(() => {
    if (childrenQuery.isFetchNextPageError && isStaleHierarchyCursorError(childrenQuery.error)) {
      void queryClient.resetQueries({ queryKey, exact: true });
    } else if (childrenQuery.hasNextPage) {
      void childrenQuery.fetchNextPage();
    } else if (childrenQuery.isError) {
      void childrenQuery.refetch();
    }
  }, [childrenQuery, queryClient, queryKey]);
  const rank = rankByKey.get(node.level);
  const canHaveChildren = rank !== undefined && rank < maxRank;
  const childRows = children.map((child) => (
    <TreeNodeBranch
      key={child.id}
      node={child}
      depth={depth + 1}
      scopeKey={scopeKey}
      expanded={expanded}
      selectedNodeId={selectedNodeId}
      knownNodes={knownNodes}
      levelTypesLoading={levelTypesLoading}
      labelByKey={labelByKey}
      maxRank={maxRank}
      rankByKey={rankByKey}
      onToggle={onToggle}
      onBranchData={onBranchData}
      onAddChild={onAddChild}
      onAddSoldier={onAddSoldier}
      onAssignCommander={onAssignCommander}
      onManageDutyManagers={onManageDutyManagers}
      onOpenPortfolio={onOpenPortfolio}
      onOpenSoldier={onOpenSoldier}
      onRename={onRename}
      onDelete={onDelete}
      onSelect={onSelect}
      onMessage={onMessage}
      t={t}
    />
  ));

  return (
    <li
      ref={setDropNodeRef}
      key={node.id}
      className={`select-none rounded ${selectedNodeId === node.id ? "bg-indigo-50 dark:bg-indigo-900/30" : ""} ${isOver ? "ring-2 ring-indigo-400" : ""}`}
    >
      <div className="py-1 px-2 rounded hover:bg-gray-50 dark:hover:bg-gray-700">
        <div className="flex flex-wrap items-center gap-1 sm:gap-2">
          {canExpand ? (
            <button
              type="button"
              className="w-6 h-7 shrink-0"
              aria-expanded={isExpanded}
              aria-label={t(isExpanded ? "team.collapse_node" : "team.expand_node", { name: node.name })}
              aria-controls={`tree-children-${node.id}`}
              onClick={() => onToggle(node)}
              data-testid={`tree-toggle-${node.id}`}
            >
              {isExpanded ? "▼" : "▶"}
            </button>
          ) : (
            <span aria-hidden="true" className="w-6 h-7 shrink-0" />
          )}
          {node.can_edit && <NodeDragHandle node={node} />}
          {labelByKey.get(node.level) && (
            <span className="shrink-0 text-xs px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-700">
              {levelTypesLoading ? node.level : labelByKey.get(node.level) ?? node.level}
            </span>
          )}
          <button
            type="button"
            className="min-w-0 truncate text-right font-medium"
            onClick={() => onSelect(node)}
            aria-current={selectedNodeId === node.id ? "true" : undefined}
            data-testid={`tree-name-${node.id}`}
          >
            {node.name}
          </button>
          {node.commander_name && node.commander_id && (
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {t("team.commander")}: <SoldierLink id={node.commander_id} name={node.commander_name} />
            </span>
          )}
          {(node.can_edit || node.dm_manageable) && (
            <div className="mr-auto">
              <PopoverDropdown
                triggerLabel=""
                badgeCount={0}
                title={t("team.actions")}
                triggerClassName="inline-flex h-7 w-7 items-center justify-center rounded border border-gray-400 text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
                panelDir="rtl"
                panelClassName="absolute top-full left-0 mt-1 z-30 bg-white dark:bg-gray-800 border dark:border-gray-600 rounded-lg shadow-xl min-w-52 flex flex-col py-1"
                triggerTestId={`tree-actions-menu-${node.id}`}
                icon={<EllipsisVertical aria-hidden="true" size={16} />}
              >
                {(close) => (
                  <>
                    {node.can_edit && canHaveChildren && <button type="button" className="px-3 py-2 text-right text-sm text-indigo-600" onClick={() => { onAddChild(node); close(); }} data-testid={`tree-add-child-${node.id}`}>{t("team.add_node")}</button>}
                    {node.can_edit && <button type="button" className="px-3 py-2 text-right text-sm text-indigo-600" onClick={() => { onAddSoldier(node.id); close(); }} data-testid={`tree-add-soldier-${node.id}`}>{t("team.add_soldier")}</button>}
                    {node.can_edit && <button type="button" className="px-3 py-2 text-right text-sm text-green-600" onClick={() => { onAssignCommander(node); close(); }} data-testid={`tree-commander-btn-${node.id}`}>{t("team.assign_commander")}</button>}
                    {node.dm_manageable && <button type="button" className="px-3 py-2 text-right text-sm text-green-700" onClick={() => { onManageDutyManagers(node.id); close(); }}>{t("team.assign_duty_managers")}</button>}
                    {node.can_edit && <button type="button" className="px-3 py-2 text-right text-sm text-amber-600" onClick={() => { onRename(node); close(); }}>{t("team.edit")}</button>}
                    {node.can_edit && <button type="button" className="px-3 py-2 text-right text-sm text-red-600" disabled={node.has_children || node.has_soldiers} onClick={() => { onDelete(node.id); close(); }}>{t("duty_config.delete")}</button>}
                  </>
                )}
              </PopoverDropdown>
            </div>
          )}
        </div>
        {node.duty_managers.length > 0 && (
          <div className="mr-8 text-xs text-gray-500 dark:text-gray-400">
            {t("team.duty_managers")}: {node.duty_managers.map((manager) => (
              <button
                key={manager.scope_id}
                type="button"
                className="ml-1 text-indigo-600 dark:text-indigo-300 hover:underline"
                onClick={() => onOpenPortfolio(manager.soldier_id, manager.name)}
              >
                {manager.name}
              </button>
            ))}
          </div>
        )}
      </div>
      {isExpanded && canExpand && (
        <ul id={`tree-children-${node.id}`} className="border-r-2 border-gray-100 mr-2" aria-label={node.name}>
          {node.has_children === true && childrenQuery.isPending && children.length === 0 && <li className="mr-4 py-2 text-sm text-gray-500" role="status">{t("team.hierarchy_loading")}</li>}
          {node.has_children === true && childrenQuery.isError && children.length === 0 && (
            <li className="mr-4 py-2 text-sm text-red-600" role="alert">
              {t("team.hierarchy_load_failed")} <button type="button" className="underline" onClick={loadMore}>{t("team.hierarchy_retry")}</button>
            </li>
          )}
          {childRows}
          <BranchTail
            hasMore={Boolean(childrenQuery.hasNextPage)}
            busy={childrenQuery.isFetchingNextPage}
            failed={childrenQuery.isFetchNextPageError}
            onLoadMore={loadMore}
            labels={{ loading: t("team.hierarchy_loading"), loadMore: t("team.hierarchy_load_more"), retry: t("team.hierarchy_retry") }}
          />
          {node.has_soldiers === true && (
            <NodeSoldiers nodeId={node.id} scopeKey={scopeKey} onOpenSoldier={onOpenSoldier} t={t} />
          )}
        </ul>
      )}
    </li>
  );
}

function NodeDragHandle({ node }: { node: NodeDTO }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `node-drag:${node.id}`,
    data: { kind: "node", id: node.id, name: node.name } satisfies DragDataNode,
  });
  return (
    <button
      ref={setNodeRef}
      type="button"
      {...attributes}
      {...listeners}
      className={`shrink-0 cursor-grab touch-none p-1 text-gray-400 active:cursor-grabbing ${isDragging ? "opacity-40" : ""}`}
      aria-label={node.name}
      title={node.name}
    >
      ⠿
    </button>
  );
}

export default function LazyHierarchyTree({
  scopeKey,
  roleOrder,
  canManageLevelTypes,
  onChanged,
  onSelectedNodeChange,
  onOpenPortfolio,
}: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { openSoldierModal } = useSoldierModal();
  const [readyScopeKey, setReadyScopeKey] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [focusedPath, setFocusedPath] = useState<NodeDTO[]>([]);
  const [branches, setBranches] = useState<Record<string, NodeDTO[]>>({});
  const [addDialog, setAddDialog] = useState<NodeDTO | null>(null);
  const [commanderDialog, setCommanderDialog] = useState<NodeDTO | null>(null);
  const [renameDialog, setRenameDialog] = useState<NodeDTO | null>(null);
  const [quickAddNode, setQuickAddNode] = useState<string | null>(null);
  const [dmDialogNodeId, setDmDialogNodeId] = useState<string | null>(null);
  const [deleteNodeId, setDeleteNodeId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [transferSuccess, setTransferSuccess] = useState<TransferSuccessInfo | null>(null);
  const [pendingTransfer, setPendingTransfer] = useState<PendingTransfer | null>(null);
  const [transferReason, setTransferReason] = useState("");
  const [activeData, setActiveData] = useState<DragData | null>(null);

  useEffect(() => {
    let current = true;
    setReadyScopeKey(null);
    setExpanded(new Set());
    setBranches({});
    void queryClient.resetQueries({ queryKey: queryKeys.hierarchyBranches(scopeKey) }).finally(() => {
      if (current) setReadyScopeKey(scopeKey);
    });
    return () => { current = false; };
  }, [queryClient, scopeKey]);

  const registerBranch = useCallback((parentId: string | null, nodes: NodeDTO[]) => {
    const key = parentId ?? "__roots__";
    setBranches((current) => {
      const previous = current[key];
      if (previous?.length === nodes.length && previous.every((node, index) => node === nodes[index])) return current;
      if (nodes.length === 0 && !previous) return current;
      return { ...current, [key]: nodes };
    });
  }, []);

  const rootKey = queryKeys.hierarchyBranch(scopeKey, null);
  const rootsQuery = useInfiniteQuery({
    queryKey: rootKey,
    queryFn: ({ pageParam, signal }) => fetchHierarchyBranchPage({ parentId: null, cursor: pageParam, signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    enabled: readyScopeKey === scopeKey,
    staleTime: Infinity,
    gcTime: 5 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const roots = useMemo(() => rootsQuery.data?.pages.flatMap((page) => page.items) ?? [], [rootsQuery.data]);
  useEffect(() => registerBranch(null, roots), [registerBranch, roots]);

  useEffect(() => {
    const timeout = window.setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => window.clearTimeout(timeout);
  }, [searchInput]);
  const searchQuery = useQuery({
    queryKey: queryKeys.hierarchySearch(scopeKey, search),
    queryFn: ({ signal }) => searchHierarchyNodes(search, signal),
    enabled: readyScopeKey === scopeKey && search.length >= 2,
    staleTime: 30_000,
  });

  const { levelTypes, loading: levelTypesLoading } = useLevelTypes();
  const { rankByKey, labelByKey, maxRank } = useMemo(() => {
    const rankByKey = new Map(levelTypes.map((levelType) => [levelType.key, levelType.rank]));
    const labelByKey = new Map(levelTypes.map((levelType) => [levelType.key, levelType.label]));
    return {
      rankByKey,
      labelByKey,
      maxRank: levelTypes.length > 0 ? Math.max(...levelTypes.map((levelType) => levelType.rank)) : 0,
    };
  }, [levelTypes]);

  const knownNodes = useMemo(() => {
    const byId = new Map<string, NodeDTO>();
    Object.values(branches).flat().forEach((node) => byId.set(node.id, node));
    focusedPath.forEach((node) => byId.set(node.id, node));
    return [...byId.values()];
  }, [branches, focusedPath]);
  const selectedNode = knownNodes.find((node) => node.id === selectedNodeId) ?? null;
  const nodesById = useMemo(() => new Map(knownNodes.map((node) => [node.id, node])), [knownNodes]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  function selectNode(node: NodeDTO) {
    setSelectedNodeId(node.id);
    onSelectedNodeChange(node);
  }

  function selectTreeNode(node: NodeDTO) {
    setFocusedPath([]);
    selectNode(node);
  }

  function toggleNode(node: NodeDTO) {
    selectTreeNode(node);
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(node.id)) next.delete(node.id);
      else next.add(node.id);
      return next;
    });
  }

  function openSearchMatch(path: NodeDTO[], node: NodeDTO) {
    setFocusedPath(path);
    selectNode(node);
  }

  function openTransferConfirmation(soldierId: string, soldierName: string, nodeId: string) {
    const destination = nodesById.get(nodeId);
    if (!destination) return;
    setTransferReason("");
    setPendingTransfer({
      soldierId,
      soldierName,
      nodeId,
      nodeName: destination.name,
      nodeLevel: labelByKey.get(destination.level) ?? destination.level,
    });
  }

  async function handleQuickAdd(nodeId: string, soldier: SoldierRosterItemDTO | null, personalNumber: string, fullName: string) {
    try {
      if (soldier) {
        openTransferConfirmation(soldier.id, soldier.full_name, nodeId);
        return;
      }
      await onboardSoldier({ personal_number: personalNumber, full_name: fullName, hierarchy_node_id: nodeId });
      setQuickAddNode(null);
      await onChanged();
    } catch (error) {
      setMessage(translateApiError(error, t, t("team.roster_load_failed")));
    }
  }

  function findApprovingCommander(nodeId: string): { id: string; name: string } | null {
    const node = nodesById.get(nodeId);
    if (!node) return null;
    for (const ancestorId of [...node.path_ids].reverse()) {
      const ancestor = nodesById.get(ancestorId);
      if (ancestor?.commander_id && ancestor.commander_name) {
        return { id: ancestor.commander_id, name: ancestor.commander_name };
      }
    }
    return null;
  }

  async function confirmTransfer() {
    if (!pendingTransfer) return;
    const transfer = pendingTransfer;
    setPendingTransfer(null);
    setQuickAddNode(null);
    try {
      await createTransferRequest(transfer.soldierId, transfer.nodeId, transferReason);
      await onChanged();
      setTransferSuccess({ commander: findApprovingCommander(transfer.nodeId) });
    } catch (error) {
      setMessage(translateApiError(error, t, t("team.roster_load_failed")));
    }
  }

  async function handleDragEnd(event: DragEndEvent) {
    setActiveData(null);
    const { active, over } = event;
    if (!over) return;
    const dragData = active.data.current as DragData | undefined;
    const overNodeId = (over.data.current as { nodeId?: string } | undefined)?.nodeId;
    if (!dragData || !overNodeId) return;

    if (dragData.kind === "soldier") {
      if (dragData.fromNodeId === overNodeId) return;
      if (dragData.isCommander) {
        setMessage(t("team.cannot_move_commander"));
        return;
      }
      openTransferConfirmation(dragData.id, dragData.name, overNodeId);
      return;
    }

    if (dragData.id === overNodeId) return;
    const target = nodesById.get(overNodeId);
    if (target?.path_ids.includes(dragData.id)) return;
    try {
      await moveNode(dragData.id, overNodeId);
      await onChanged();
    } catch (error) {
      setMessage(translateApiError(error, t, t("team.roster_load_failed")));
    }
  }

  const rosterColumns = useMemo<ColDef<SoldierRosterItemDTO>[]>(() => [
    { id: "full_name", header: t("team.full_name"), cell: (soldier) => soldier.full_name, sortValue: (soldier) => soldier.full_name, filterValue: (soldier) => soldier.full_name },
    { id: "personal_number", header: t("team.personal_number"), cell: (soldier) => soldier.personal_number, sortValue: (soldier) => soldier.personal_number, filterValue: (soldier) => soldier.personal_number },
    { id: "role", header: t("team.role"), cell: (soldier) => t(`role.${soldier.role}`), sortValue: (soldier) => t(`role.${soldier.role}`) },
    { id: "telegram", header: t("team.telegram"), cell: (soldier) => <TelegramBadge linked={soldier.telegram_linked} />, sortValue: (soldier) => soldier.telegram_linked ? 0 : 1 },
    {
      id: "actions",
      header: "",
      cell: (soldier) => (
        <span className="flex items-center gap-2">
          <SoldierDragHandle soldier={soldier} nodeId={selectedNode?.id ?? ""} />
          <button type="button" className="text-indigo-600 dark:text-indigo-300" onClick={() => void openSoldierModal(soldier.id, onChanged)}>
            {t("team.edit")}
          </button>
        </span>
      ),
    },
  ], [onChanged, openSoldierModal, selectedNode?.id, t]);

  const loadRootsMore = useCallback(() => {
    if (rootsQuery.isFetchNextPageError && isStaleHierarchyCursorError(rootsQuery.error)) {
      void queryClient.resetQueries({ queryKey: rootKey, exact: true });
    } else if (rootsQuery.hasNextPage) {
      void rootsQuery.fetchNextPage();
    } else if (rootsQuery.isError) {
      void rootsQuery.refetch();
    }
  }, [queryClient, rootKey, rootsQuery]);

  useEffect(() => {
    let lastReset = 0;
    const resetBranches = () => {
      // visibilitychange also fires when the page is hidden, including while
      // the document unloads on navigation; a reset then starts a fetch that
      // the unload immediately aborts. Only refresh on the way back in.
      if (document.visibilityState !== "visible") return;
      const now = Date.now();
      if (now - lastReset < 1000) return;
      lastReset = now;
      void queryClient.resetQueries({ queryKey: queryKeys.hierarchyBranches(scopeKey) });
      void queryClient.resetQueries({ queryKey: ["hierarchy", "search", scopeKey] });
    };
    window.addEventListener("focus", resetBranches);
    document.addEventListener("visibilitychange", resetBranches);
    return () => {
      window.removeEventListener("focus", resetBranches);
      document.removeEventListener("visibilitychange", resetBranches);
    };
  }, [queryClient, scopeKey]);

  const openAddSoldier = useCallback((nodeId: string) => setQuickAddNode(nodeId), []);
  const openAddChild = useCallback((node: NodeDTO) => setAddDialog(node), []);
  const openCommander = useCallback((node: NodeDTO) => setCommanderDialog(node), []);
  const openDutyManagers = useCallback((nodeId: string) => setDmDialogNodeId(nodeId), []);
  const openRename = useCallback((node: NodeDTO) => setRenameDialog(node), []);
  const openDelete = useCallback((nodeId: string) => setDeleteNodeId(nodeId), []);
  const onMessage = useCallback((nextMessage: string) => setMessage(nextMessage), []);

  async function confirmDeleteNode() {
    if (!deleteNodeId) return;
    const id = deleteNodeId;
    setDeleteNodeId(null);
    try {
      await deleteNode(id);
      await onChanged();
    } catch (error) {
      setMessage(translateApiError(error, t, t("team.hierarchy_load_failed")));
    }
  }

  return (
    <section className="space-y-3" data-testid="lazy-hierarchy-tree">
      <label className="block max-w-xl">
        <span className="block text-xs text-gray-600 dark:text-gray-300">{t("team.hierarchy_search")}</span>
        <input
          className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          value={searchInput}
          onChange={(event) => {
            setSearchInput(event.target.value);
            setFocusedPath([]);
          }}
          placeholder={t("team.hierarchy_search_placeholder")}
          data-testid="hierarchy-search"
        />
      </label>
      {searchQuery.isError && <p role="alert" className="text-sm text-red-600">{t("team.hierarchy_search_failed")}</p>}
      {searchQuery.isFetching && search.length >= 2 && <p role="status" className="text-sm text-gray-500">{t("team.hierarchy_search_loading")}</p>}
      {searchQuery.data && searchQuery.data.matches.length > 0 && (
        <ul className="max-h-56 max-w-xl overflow-y-auto rounded border dark:border-gray-700" data-testid="hierarchy-search-results">
          {searchQuery.data.matches.map((match) => (
            <li key={match.node.id}>
              <button type="button" className="block w-full px-3 py-2 text-right text-sm hover:bg-indigo-50 dark:hover:bg-indigo-900/40" onClick={() => openSearchMatch(match.path, match.node)}>
                <span className="block font-medium">{match.node.name}</span>
                <span className="block text-xs text-gray-500">{match.path.map((part) => part.name).join(" › ")}</span>
              </button>
            </li>
          ))}
          {searchQuery.data.has_more && <li className="px-3 py-2 text-xs text-gray-500">{t("team.hierarchy_search_more")}</li>}
        </ul>
      )}
      {search.length >= 2 && searchQuery.data?.matches.length === 0 && !searchQuery.isFetching && !searchQuery.isError && (
        <p className="text-sm text-gray-500">{t("team.hierarchy_search_empty")}</p>
      )}
      <DndContext
        sensors={sensors}
        onDragStart={(event) => { const data = event.active.data.current; if (data) setActiveData(data as DragData); }}
        onDragCancel={() => setActiveData(null)}
        onDragEnd={(event) => void handleDragEnd(event)}
      >
        <ul className="text-sm text-gray-900 dark:text-white mr-4" data-testid="node-tree" aria-label={t("team.title")} tabIndex={-1}>
          {rootsQuery.isPending && roots.length === 0 && <li className="py-2 text-gray-500" role="status">{t("team.hierarchy_loading")}</li>}
          {rootsQuery.isError && roots.length === 0 && (
            <li className="py-2 text-red-600" role="alert">{t("team.hierarchy_load_failed")} <button type="button" className="underline" onClick={loadRootsMore}>{t("team.hierarchy_retry")}</button></li>
          )}
          {roots.length > 0 && <li className="px-2 py-1 mb-1 font-semibold border-b border-gray-200 dark:border-gray-700">{t("common.whole_org")}</li>}
          {focusedPath.length > 0 && (
            <li className="mb-2 rounded border border-indigo-200 bg-indigo-50/50 px-3 py-2 dark:border-indigo-900 dark:bg-indigo-950/30" data-testid="hierarchy-search-path-overlay">
              <span className="block text-xs text-gray-500 dark:text-gray-400">{t("team.hierarchy_search_path")}</span>
              <ul role="tree" aria-label={t("team.hierarchy_search_path")} className="mt-1 text-sm">
                <SearchPathTreeItem
                  path={focusedPath}
                  index={0}
                  selectedNodeId={selectedNodeId}
                  onSelect={selectNode}
                />
              </ul>
            </li>
          )}
          {roots.map((node) => (
            <TreeNodeBranch
              key={node.id}
              node={node}
              depth={0}
              scopeKey={scopeKey}
              expanded={expanded}
              selectedNodeId={selectedNodeId}
              knownNodes={knownNodes}
              levelTypesLoading={levelTypesLoading}
              labelByKey={labelByKey}
              maxRank={maxRank}
              rankByKey={rankByKey}
              onToggle={toggleNode}
              onBranchData={registerBranch}
              onAddChild={openAddChild}
              onAddSoldier={openAddSoldier}
              onAssignCommander={openCommander}
              onManageDutyManagers={openDutyManagers}
              onOpenPortfolio={onOpenPortfolio}
              onOpenSoldier={(soldierId) => void openSoldierModal(soldierId, onChanged)}
              onRename={openRename}
              onDelete={openDelete}
              onSelect={selectTreeNode}
              onMessage={onMessage}
              t={t}
            />
          ))}
          <BranchTail
            hasMore={Boolean(rootsQuery.hasNextPage)}
            busy={rootsQuery.isFetchingNextPage}
            failed={rootsQuery.isFetchNextPageError}
            onLoadMore={loadRootsMore}
            labels={{ loading: t("team.hierarchy_loading"), loadMore: t("team.hierarchy_load_more"), retry: t("team.hierarchy_retry") }}
          />
        </ul>
        <DragOverlay>
          {activeData && <div className="bg-white dark:bg-gray-800 border border-indigo-300 rounded px-3 py-1 text-sm shadow-lg opacity-90">{activeData.name}</div>}
        </DragOverlay>

        {selectedNode && (
          <section className="mt-4 space-y-2" data-testid="selected-node-roster">
            <h3 className="font-semibold">{t("team.soldiers_in_node", { name: selectedNode.name })}</h3>
            <CursorPagedTable
              columns={rosterColumns}
              queryKey={queryKeys.soldierRoster()}
              scopeKey={scopeKey}
              filterKey={{ node_id: selectedNode.id, direct_node_only: true, active_only: true }}
              roleOrder={roleOrder}
              fetchPage={({ cursor, search: rosterSearch, sort, descending, roleOrder: localizedRoleOrder, pageSize, signal }) =>
                listSoldierRosterPage({
                  cursor,
                  node_id: selectedNode.id,
                  direct_node_only: true,
                  active_only: true,
                  search: rosterSearch,
                  sort: sort as SoldierRosterSort,
                  descending,
                  role_order: (localizedRoleOrder ?? []).join(","),
                  page_size: pageSize,
                  signal,
                })
              }
              getRowId={(soldier) => soldier.id}
              tableLabel={t("team.soldiers_in_node", { name: selectedNode.name })}
              labels={{
                searchLabel: t("team.roster_search_label"),
                searchPlaceholder: t("team.roster_search_placeholder"),
                loading: t("team.roster_loading"),
                loadingMore: t("team.roster_loading_more"),
                loadMore: t("team.roster_load_more"),
                retry: t("team.roster_retry"),
                loadFailed: t("team.roster_load_failed"),
                emptyMessage: t("team.no_soldiers"),
                loaded: (count) => t("team.roster_loaded", { count }),
                allLoaded: (count) => t("team.roster_all_loaded", { count }),
                keyboardHint: t("team.roster_keyboard_hint"),
              }}
              isCursorStaleError={isStaleSoldierRosterCursorError}
              pageSize={100}
              initialSort="full_name"
              testId="selected-node-soldier-table"
            />
          </section>
        )}
      </DndContext>

      {quickAddNode && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4" onClick={() => setQuickAddNode(null)}>
          <div className="w-full max-w-md rounded-lg bg-white p-4 shadow-xl dark:bg-gray-800" onClick={(event) => event.stopPropagation()}>
            <h3 className="mb-2 font-semibold">{t("team.add_soldier")}</h3>
            <SoldierSearchAutocomplete
              onSelect={(soldier) => { if (soldier) void handleQuickAdd(quickAddNode, soldier, "", ""); }}
              onCreateNew={(personalNumber, fullName) => void handleQuickAdd(quickAddNode, null, personalNumber, fullName)}
            />
            <button type="button" className="mt-3 border rounded px-3 py-1 dark:border-gray-600" onClick={() => setQuickAddNode(null)}>{t("team.cancel")}</button>
          </div>
        </div>
      )}
      {addDialog && <AddChildNodeDialog parent={addDialog} onClose={() => setAddDialog(null)} onCreated={onChanged} />}
      {commanderDialog && <AssignCommanderDialog node={commanderDialog} onClose={() => setCommanderDialog(null)} onAssigned={onChanged} />}
      {dmDialogNodeId && nodesById.get(dmDialogNodeId) && (
        <AssignDutyManagersDialog
          node={nodesById.get(dmDialogNodeId)!}
          onClose={() => setDmDialogNodeId(null)}
          onChanged={onChanged}
        />
      )}
      {renameDialog && (
        <EditNodeDialog
          nodeId={renameDialog.id}
          currentName={renameDialog.name}
          currentLevel={renameDialog.level}
          onClose={() => setRenameDialog(null)}
          parentRank={rankByKey.get(nodesById.get(renameDialog.parent_id ?? "")?.level ?? "") ?? null}
          minChildRank={Math.min(
            ...knownNodes
              .filter((candidate) => candidate.parent_id === renameDialog.id)
              .map((candidate) => rankByKey.get(candidate.level) ?? Number.POSITIVE_INFINITY),
            Number.POSITIVE_INFINITY,
          )}
          isAdmin={canManageLevelTypes}
          nodesUsingLevel={(key) => knownNodes.some((candidate) => candidate.level === key)}
          onRenamed={onChanged}
        />
      )}
      <ConfirmDialog
        open={deleteNodeId !== null}
        title={t("team.delete_node_title")}
        message={t("team.confirm_delete_node")}
        confirmLabel={t("duty_config.delete")}
        danger
        onConfirm={() => void confirmDeleteNode()}
        onClose={() => setDeleteNodeId(null)}
      />
      <ConfirmDialog
        open={pendingTransfer !== null}
        title={t("team.transfer_confirm_title")}
        message={pendingTransfer ? t("team.transfer_confirm_message").replace("{{soldier}}", pendingTransfer.soldierName).replace("{{level}}", pendingTransfer.nodeLevel).replace("{{node}}", pendingTransfer.nodeName) : ""}
        confirmLabel={t("approvals.approve")}
        onConfirm={() => void confirmTransfer()}
        onClose={() => setPendingTransfer(null)}
      >
        <label className="block text-sm">
          <span className="block mb-1">{t("team.transfer_reason_label")}</span>
          <textarea className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600" value={transferReason} onChange={(event) => setTransferReason(event.target.value)} placeholder={t("team.transfer_reason_placeholder")} data-testid="transfer-reason" />
        </label>
      </ConfirmDialog>
      {transferSuccess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setTransferSuccess(null)}>
          <div className="max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-gray-800" dir="rtl" onClick={(event) => event.stopPropagation()}>
            <h3 className="mb-3 text-lg font-bold">{t("team.transfer_success_title")}</h3>
            {transferSuccess.commander ? (
              <p>{t("team.transfer_success_message", { commander: transferSuccess.commander.name })} <SoldierLink id={transferSuccess.commander.id} name={transferSuccess.commander.name} /></p>
            ) : <p>{t("team.transfer_success_message_no_commander")}</p>}
            <button type="button" className="mt-4 rounded bg-indigo-600 px-3 py-1 text-white" onClick={() => setTransferSuccess(null)}>{t("team.cancel")}</button>
          </div>
        </div>
      )}
      {message && <MessageDialog open title={t("common.error")} message={message} onClose={() => setMessage(null)} />}
    </section>
  );
}
