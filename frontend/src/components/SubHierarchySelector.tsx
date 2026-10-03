import { useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { fetchHierarchyBranchPage, isStaleHierarchyCursorError, type NodeDTO } from "../api/hierarchy";
import { getTransparencyAuthorizationScope } from "../api/auth";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";

interface Props { value: string[]; onChange: (selected: string[]) => void; prompt?: string; }

function Branch({ node, depth, value, onToggle, scopeKey }: {
  node: NodeDTO; depth: number; value: string[]; onToggle: (id: string) => void; scopeKey: string | null;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const queryKey = queryKeys.hierarchyBranch(scopeKey, node.id);
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) => fetchHierarchyBranchPage({ parentId: node.id, cursor: pageParam, signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.has_more ? page.next_cursor ?? undefined : undefined,
    enabled: expanded && node.has_children === true,
    retry: false,
    staleTime: 30_000,
    gcTime: 5 * 60 * 1000,
  });
  const children = [...new Map((query.data?.pages.flatMap((page) => page.items) ?? []).map((child) => [child.id, child])).values()];
  const retry = () => {
    if (query.isFetchNextPageError && isStaleHierarchyCursorError(query.error)) void queryClient.resetQueries({ queryKey, exact: true });
    else if (query.hasNextPage) void query.fetchNextPage();
    else void query.refetch();
  };

  return (
    <li>
      <div className="flex items-center gap-1 rounded py-1 hover:bg-gray-50 dark:hover:bg-gray-700" style={{ paddingRight: `${depth * 16 + 4}px` }}>
        {node.has_children ? <button type="button" onClick={() => setExpanded((current) => !current)} className="flex h-5 w-5 shrink-0 items-center justify-center text-gray-500" aria-label={`${expanded ? t("team.hierarchy_collapse") : t("team.hierarchy_expand")} ${node.name}`} aria-expanded={expanded} aria-controls={`sub-hierarchy-children-${node.id}`}>{expanded ? "▾" : "▸"}</button> : <span aria-hidden="true" className="h-5 w-5 shrink-0" />}
        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
          <input type="checkbox" checked={value.includes(node.id)} onChange={() => onToggle(node.id)} className="shrink-0 rounded" />
          <span className="truncate text-sm">{node.name}</span>
        </label>
      </div>
      {expanded && node.has_children && <ul id={`sub-hierarchy-children-${node.id}`}>
        {query.isPending && children.length === 0 && <li role="status" className="py-1 text-xs text-gray-500">{t("team.hierarchy_loading")}</li>}
        {query.isError && children.length === 0 && <li role="alert" className="py-1 text-xs text-red-600">{t("team.hierarchy_load_failed")} <button type="button" className="underline" onClick={retry}>{t("team.hierarchy_retry")}</button></li>}
        {children.map((child) => <Branch key={child.id} node={child} depth={depth + 1} value={value} onToggle={onToggle} scopeKey={scopeKey} />)}
        {query.isFetchNextPageError && children.length > 0 && <li role="alert" className="py-1 text-xs text-red-600">{t("team.hierarchy_load_failed")} <button type="button" className="underline" onClick={retry}>{t("team.hierarchy_retry")}</button></li>}
        {query.isFetchingNextPage && <li role="status" className="py-1 text-xs text-gray-500">{t("team.hierarchy_loading")}</li>}
        {query.hasNextPage && !query.isFetchingNextPage && !query.isFetchNextPageError && <li><button type="button" className="py-1 text-xs text-indigo-600 underline" onClick={retry}>{t("team.hierarchy_load_more")}</button></li>}
      </ul>}
    </li>
  );
}

export default function SubHierarchySelector({ value, onChange, prompt }: Props) {
  const { t } = useTranslation();
  const { user, authScopeReady } = useAuth();
  const scopeKey = authScopeReady ? getTransparencyAuthorizationScope(user) : null;
  const queryClient = useQueryClient();
  const rootKey = queryKeys.hierarchyBranch(scopeKey, null);
  const rootsQuery = useInfiniteQuery({
    queryKey: rootKey,
    queryFn: ({ pageParam, signal }) => fetchHierarchyBranchPage({ parentId: null, cursor: pageParam, signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.has_more ? page.next_cursor ?? undefined : undefined,
    enabled: authScopeReady,
    retry: false,
    staleTime: 30_000,
    gcTime: 5 * 60 * 1000,
  });
  const roots = [...new Map((rootsQuery.data?.pages.flatMap((page) => page.items) ?? []).map((node) => [node.id, node])).values()];
  const toggleNode = (nodeId: string) => onChange(value.includes(nodeId) ? value.filter((id) => id !== nodeId) : [...value, nodeId]);
  const retryRoots = () => {
    if (rootsQuery.isFetchNextPageError && isStaleHierarchyCursorError(rootsQuery.error)) void queryClient.resetQueries({ queryKey: rootKey, exact: true });
    else if (rootsQuery.hasNextPage) void rootsQuery.fetchNextPage();
    else void rootsQuery.refetch();
  };

  return <div className="max-h-60 overflow-y-auto rounded border p-2 dark:border-gray-600 dark:bg-gray-800" data-testid="sub-hierarchy-selector">
    <p className="mb-2 text-xs text-gray-500">{prompt ?? t("algorithm.select_eligible_nodes")}</p>
    <ul>
      {rootsQuery.isPending && roots.length === 0 && <li role="status" className="text-xs text-gray-500">{t("team.hierarchy_loading")}</li>}
      {rootsQuery.isError && roots.length === 0 && <li role="alert" className="text-xs text-red-600">{t("team.hierarchy_load_failed")} <button type="button" className="underline" onClick={retryRoots}>{t("team.hierarchy_retry")}</button></li>}
      {roots.map((node) => <Branch key={node.id} node={node} depth={0} value={value} onToggle={toggleNode} scopeKey={scopeKey} />)}
      {rootsQuery.isFetchNextPageError && roots.length > 0 && <li role="alert" className="text-xs text-red-600">{t("team.hierarchy_load_failed")} <button type="button" className="underline" onClick={retryRoots}>{t("team.hierarchy_retry")}</button></li>}
      {rootsQuery.isFetchingNextPage && <li role="status" className="text-xs text-gray-500">{t("team.hierarchy_loading")}</li>}
      {rootsQuery.hasNextPage && !rootsQuery.isFetchingNextPage && !rootsQuery.isFetchNextPageError && <li><button type="button" className="py-1 text-xs text-indigo-600 underline" onClick={retryRoots}>{t("team.hierarchy_load_more")}</button></li>}
    </ul>
  </div>;
}
