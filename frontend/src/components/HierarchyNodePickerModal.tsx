import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { getTransparencyAuthorizationScope } from "../api/auth";
import {
  fetchHierarchyBranchPage,
  HierarchySearchMatchDTO,
  isStaleHierarchyCursorError,
  NodeDTO,
  searchHierarchyNodes,
} from "../api/hierarchy";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  onClose: () => void;
  onPicked: (nodeId: string, nodeName: string, path?: string[]) => void;
}

function useNearEndPrefetch({
  root,
  enabled,
  onPrefetch,
}: {
  root: HTMLElement | null;
  enabled: boolean;
  onPrefetch: () => void;
}) {
  const sentinelRef = useRef<HTMLDivElement>(null);
  const armedRef = useRef(true);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!enabled || !root || !sentinel || typeof IntersectionObserver === "undefined") return;

    let active = true;
    const observer = new IntersectionObserver((entries) => {
      if (!active) return;
      for (const entry of entries) {
        if (entry.target !== sentinel) continue;
        if (!entry.isIntersecting) {
          armedRef.current = true;
        } else if (armedRef.current) {
          armedRef.current = false;
          onPrefetch();
        }
      }
    }, { root, rootMargin: "160px 0px" });
    observer.observe(sentinel);

    return () => {
      active = false;
      observer.disconnect();
    };
  }, [enabled, onPrefetch, root]);

  return sentinelRef;
}

function matchPath(match: HierarchySearchMatchDTO): NodeDTO[] {
  return match.path.at(-1)?.id === match.node.id ? match.path : [...match.path, match.node];
}

function BranchContinuation({
  visible,
  busy,
  failed,
  onLoadMore,
  t,
}: {
  visible: boolean;
  busy: boolean;
  failed: boolean;
  onLoadMore: () => void;
  t: (key: string) => string;
}) {
  if (!visible && !failed) return null;

  return (
    <button
      type="button"
      className="px-2 py-1 text-xs text-indigo-600 hover:underline disabled:text-gray-400"
      onClick={onLoadMore}
      disabled={busy}
      aria-label={t(busy ? "team.hierarchy_loading" : failed ? "team.hierarchy_retry" : "team.hierarchy_load_more")}
    >
      {t(busy ? "team.hierarchy_loading" : failed ? "team.hierarchy_retry" : "team.hierarchy_load_more")}
    </button>
  );
}

function BranchNode({
  node,
  depth,
  ancestorNames,
  scopeKey,
  scrollRoot,
  onPicked,
}: {
  node: NodeDTO;
  depth: number;
  ancestorNames: string[];
  scopeKey: string;
  scrollRoot: HTMLElement | null;
  onPicked: Props["onPicked"];
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const queryKey = queryKeys.hierarchyBranch(scopeKey, node.id);
  const childrenQuery = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) =>
      fetchHierarchyBranchPage({ parentId: node.id, cursor: pageParam, signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    enabled: expanded && node.has_children === true,
    retry: false,
    staleTime: 30_000,
    gcTime: 5 * 60 * 1000,
  });
  const children = useMemo(
    () => childrenQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [childrenQuery.data],
  );
  const hasChildren = node.has_children === true;
  const canPrefetchChildren = Boolean(
    expanded && childrenQuery.hasNextPage && !childrenQuery.isFetching &&
    !childrenQuery.isError && !childrenQuery.isFetchNextPageError,
  );
  const fetchNextChildrenPage = childrenQuery.fetchNextPage;
  const prefetchChildren = useCallback(() => {
    void fetchNextChildrenPage();
  }, [fetchNextChildrenPage]);
  const childSentinelRef = useNearEndPrefetch({
    root: scrollRoot,
    enabled: canPrefetchChildren,
    onPrefetch: prefetchChildren,
  });

  function loadMore() {
    if (childrenQuery.isFetchNextPageError && isStaleHierarchyCursorError(childrenQuery.error)) {
      void queryClient.resetQueries({ queryKey, exact: true });
    } else if (childrenQuery.hasNextPage) {
      void childrenQuery.fetchNextPage();
    } else if (childrenQuery.isError) {
      void childrenQuery.refetch();
    }
  }

  return (
    <li>
      <div
        className="flex items-center justify-between gap-1 rounded py-1 hover:bg-gray-50 dark:hover:bg-gray-700"
        style={{ paddingRight: `${depth * 16 + 4}px` }}
      >
        <div className="flex min-w-0 flex-1 items-center gap-1">
          {hasChildren ? (
            <button
              type="button"
              onClick={() => setExpanded((current) => !current)}
              className="flex h-5 w-5 shrink-0 items-center justify-center text-gray-500"
              aria-label={`${expanded ? "כווץ" : "הרחב"} ${node.name}`}
              aria-expanded={expanded}
              aria-controls={`picker-children-${node.id}`}
              data-testid={`picker-tree-toggle-${node.id}`}
            >
              {expanded ? "▾" : "▸"}
            </button>
          ) : (
            <span aria-hidden="true" className="h-5 w-5 shrink-0" />
          )}
          <span className="truncate text-sm dark:text-gray-100">{node.name}</span>
        </div>
        <button
          type="button"
          className="shrink-0 text-xs text-indigo-600 hover:underline"
          onClick={() => onPicked(node.id, node.name, [...ancestorNames, node.name])}
          data-testid={`picker-select-node-${node.id}`}
        >
          בחר
        </button>
      </div>
      {expanded && hasChildren && (
        <ul id={`picker-children-${node.id}`}>
          {childrenQuery.isPending && children.length === 0 && (
            <li role="status" className="px-2 py-1 text-xs text-gray-500">{t("team.hierarchy_loading")}</li>
          )}
          {childrenQuery.isError && children.length === 0 && (
            <li role="alert" className="px-2 py-1 text-xs text-red-600">
              {t("team.hierarchy_load_failed")}{" "}
              <button type="button" className="underline" onClick={loadMore}>{t("team.hierarchy_retry")}</button>
            </li>
          )}
          {children.map((child) => (
            <BranchNode
              key={child.id}
              node={child}
              depth={depth + 1}
              ancestorNames={[...ancestorNames, node.name]}
              scopeKey={scopeKey}
              scrollRoot={scrollRoot}
              onPicked={onPicked}
            />
          ))}
          {!childrenQuery.isPending && !childrenQuery.isError && children.length === 0 && (
            <li className="px-2 py-1 text-xs text-gray-400">אין יחידות נוספות</li>
          )}
          <li>
            <div
              ref={childSentinelRef}
              className="h-px"
              aria-hidden="true"
              data-testid={`picker-branch-prefetch-sentinel-${node.id}`}
            />
            <BranchContinuation
              visible={Boolean(childrenQuery.hasNextPage)}
              busy={childrenQuery.isFetchingNextPage}
              failed={childrenQuery.isFetchNextPageError}
              onLoadMore={loadMore}
              t={t}
            />
          </li>
        </ul>
      )}
    </li>
  );
}

export default function HierarchyNodePickerModal({ onClose, onPicked }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [scrollRoot, setScrollRoot] = useState<HTMLElement | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const authorizationScope = useMemo(
    () => JSON.stringify({
      normalizedScope: getTransparencyAuthorizationScope(user),
      actorId: user?.id ?? null,
      role: user?.role ?? null,
    }),
    [user],
  );
  const rootKey = queryKeys.hierarchyBranch(authorizationScope, null);
  const rootsQuery = useInfiniteQuery({
    queryKey: rootKey,
    queryFn: ({ pageParam, signal }) =>
      fetchHierarchyBranchPage({ parentId: null, cursor: pageParam, signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    enabled: Boolean(user),
    retry: false,
    staleTime: 30_000,
    gcTime: 5 * 60 * 1000,
  });
  const roots = useMemo(
    () => rootsQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [rootsQuery.data],
  );
  const canPrefetchRoots = Boolean(
    rootsQuery.hasNextPage && !rootsQuery.isFetching &&
    !rootsQuery.isError && !rootsQuery.isFetchNextPageError,
  );
  const fetchNextRootPage = rootsQuery.fetchNextPage;
  const prefetchRoots = useCallback(() => {
    void fetchNextRootPage();
  }, [fetchNextRootPage]);
  const rootSentinelRef = useNearEndPrefetch({
    root: scrollRoot,
    enabled: canPrefetchRoots,
    onPrefetch: prefetchRoots,
  });

  useEffect(() => {
    const timeout = window.setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => window.clearTimeout(timeout);
  }, [searchInput]);
  const searchQuery = useQuery({
    queryKey: queryKeys.hierarchySearch(authorizationScope, search),
    queryFn: ({ signal }) => searchHierarchyNodes(search, signal),
    enabled: Boolean(user && search.length >= 2),
    staleTime: 30_000,
  });
  const normalizedSearchInput = searchInput.trim();
  const searchIsCurrent = normalizedSearchInput === search;
  const searching = normalizedSearchInput.length > 0;
  const matches = searchIsCurrent ? searchQuery.data?.matches ?? [] : [];

  function loadMoreRoots() {
    if (rootsQuery.isFetchNextPageError && isStaleHierarchyCursorError(rootsQuery.error)) {
      void queryClient.resetQueries({ queryKey: rootKey, exact: true });
    } else if (rootsQuery.hasNextPage) {
      void rootsQuery.fetchNextPage();
    } else if (rootsQuery.isError) {
      void rootsQuery.refetch();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={(event) => { event.stopPropagation(); onClose(); }}>
      <div
        className="flex max-h-[80dvh] w-96 flex-col rounded-lg bg-white p-6 shadow-xl dark:bg-gray-800"
        dir="rtl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-semibold dark:text-gray-100">בחר יחידה</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="סגור">✕</button>
        </div>

        <input
          className="mb-3 w-full rounded border p-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          placeholder="חיפוש..."
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          aria-label="חיפוש יחידה"
        />

        {searching ? (
          <div className="flex-1 overflow-y-auto space-y-1" role="region" aria-label="תוצאות חיפוש יחידות">
            {!searchIsCurrent && <p role="status" className="text-xs text-gray-400">{t("team.hierarchy_search_loading")}</p>}
            {searchIsCurrent && search.length >= 2 && searchQuery.isFetching && (
              <p role="status" className="text-xs text-gray-400">{t("team.hierarchy_search_loading")}</p>
            )}
            {searchIsCurrent && search.length >= 2 && searchQuery.isError && (
              <p role="alert" className="text-xs text-red-500">
                {t("team.hierarchy_search_failed")}{" "}
                <button type="button" className="underline" onClick={() => void searchQuery.refetch()}>
                  {t("team.hierarchy_retry")}
                </button>
            </p>
            )}
            {searchIsCurrent && search.length === 1 && (
              <p role="status" className="text-xs text-gray-500">יש להקליד לפחות 2 תווים כדי לחפש</p>
            )}
            {matches.map((match) => (
              <div
                key={match.node.id}
                className="flex items-center justify-between gap-2 rounded p-1.5 text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <div className="min-w-0">
                  <span className="block truncate dark:text-gray-100">{match.node.name}</span>
                  <span className="block truncate text-xs text-gray-500 dark:text-gray-400">
                    {matchPath(match).map((part) => part.name).join(" › ")}
                  </span>
                </div>
                <button
                  type="button"
                  className="shrink-0 text-xs text-indigo-600 hover:underline"
                  onClick={() => onPicked(match.node.id, match.node.name, matchPath(match).map((part) => part.name))}
                  data-testid={`picker-select-node-${match.node.id}`}
                >
                  בחר
                </button>
              </div>
            ))}
            {searchIsCurrent && search.length >= 2 && matches.length === 0 && !searchQuery.isFetching && !searchQuery.isError && (
              <p className="py-4 text-center text-xs text-gray-400">לא נמצאו יחידות</p>
            )}
            {searchIsCurrent && searchQuery.data?.has_more && (
              <p className="px-2 py-1 text-xs text-gray-500" role="note">{t("team.hierarchy_search_more")}</p>
            )}
          </div>
        ) : (
          <div ref={setScrollRoot} className="flex-1 space-y-1 overflow-y-auto">
            <ul aria-label="היררכיית יחידות">
              {rootsQuery.isPending && roots.length === 0 && (
                <li role="status" className="py-2 text-xs text-gray-400">{t("team.hierarchy_loading")}</li>
              )}
              {rootsQuery.isError && roots.length === 0 && (
                <li role="alert" className="py-2 text-xs text-red-500">
                  {t("team.hierarchy_load_failed")}{" "}
                  <button type="button" className="underline" onClick={loadMoreRoots}>{t("team.hierarchy_retry")}</button>
                </li>
              )}
              {roots.map((node) => (
                <BranchNode
                  key={node.id}
                  node={node}
                  depth={0}
                  ancestorNames={[]}
                  scopeKey={authorizationScope}
                  scrollRoot={scrollRoot}
                  onPicked={onPicked}
                />
              ))}
              {!rootsQuery.isPending && !rootsQuery.isError && roots.length === 0 && (
                <li className="py-2 text-center text-xs text-gray-400">אין יחידות להצגה</li>
              )}
              <li>
                <div
                  ref={rootSentinelRef}
                  className="h-px"
                  aria-hidden="true"
                  data-testid="picker-root-prefetch-sentinel"
                />
                <BranchContinuation
                  visible={Boolean(rootsQuery.hasNextPage)}
                  busy={rootsQuery.isFetchingNextPage}
                  failed={rootsQuery.isFetchNextPageError}
                  onLoadMore={loadMoreRoots}
                  t={t}
                />
              </li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
