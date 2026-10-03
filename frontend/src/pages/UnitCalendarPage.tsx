import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";

import { getTransparencyAuthorizationScope } from "../api/auth";
import {
  fetchHierarchyBranchPage,
  isStaleHierarchyCursorError,
  NodeDTO,
  searchHierarchyNodes,
} from "../api/hierarchy";
import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import UnitCalendar from "../components/UnitCalendar";
import { useAuth } from "../auth/AuthContext";

export default function UnitCalendarPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [nodeId, setNodeId] = useState<string>("");
  const [selectedNodeLabel, setSelectedNodeLabel] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [browsePath, setBrowsePath] = useState<NodeDTO[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);

  const authorizationScope = JSON.stringify({
    normalizedScope: getTransparencyAuthorizationScope(user),
    actorId: user?.id ?? null,
    role: user?.role ?? null,
  });
  const rootsQuery = useInfiniteQuery({
    queryKey: queryKeys.hierarchyBranch(authorizationScope, null),
    queryFn: ({ pageParam, signal }) =>
      fetchHierarchyBranchPage({ parentId: null, cursor: pageParam, signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    enabled: Boolean(user),
  });
  const roots = useMemo(
    () => rootsQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [rootsQuery.data],
  );

  const currentParentId = browsePath.at(-1)?.id ?? null;
  const childrenQuery = useInfiniteQuery({
    queryKey: queryKeys.hierarchyBranch(authorizationScope, currentParentId ?? "__inactive__"),
    queryFn: ({ pageParam, signal }) =>
      fetchHierarchyBranchPage({ parentId: currentParentId, cursor: pageParam, signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    enabled: Boolean(user && currentParentId),
  });
  const currentNodes = useMemo(
    () =>
      currentParentId
        ? childrenQuery.data?.pages.flatMap((page) => page.items) ?? []
        : roots,
    [childrenQuery.data, currentParentId, roots],
  );
  const currentBranchQuery = currentParentId ? childrenQuery : rootsQuery;
  const currentBranchKey = queryKeys.hierarchyBranch(authorizationScope, currentParentId);

  useEffect(() => {
    const timeout = window.setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => window.clearTimeout(timeout);
  }, [searchInput]);
  const searchQuery = useQuery({
    queryKey: queryKeys.hierarchySearch(authorizationScope, search),
    queryFn: ({ signal }) => searchHierarchyNodes(search, signal),
    enabled: Boolean(user && search),
    staleTime: 30_000,
  });
  const normalizedSearchInput = searchInput.trim();
  const searchIsCurrent = normalizedSearchInput === search;
  const searchMatches = searchIsCurrent ? searchQuery.data?.matches ?? [] : [];
  const searching = normalizedSearchInput.length > 0;
  const keyboardOptionCount = searching ? searchMatches.length : currentNodes.length;
  const activeOptionId = pickerOpen
    ? searching
      ? searchMatches[activeIndex]
        ? `unit-calendar-node-option-${searchMatches[activeIndex].node.id}`
        : undefined
      : currentNodes[activeIndex]
        ? `unit-calendar-node-option-${currentNodes[activeIndex].id}`
        : undefined
    : undefined;

  // Legacy /hierarchy/tree chose its first returned root, but its SELECT was
  // unordered. The bounded endpoint makes the multi-root default deterministic.
  const rootNodeId = roots[0]?.id ?? "";
  const effectiveNodeId = nodeId || rootNodeId;

  function selectNode(node: NodeDTO, path: NodeDTO[]) {
    setNodeId(node.id);
    setSelectedNodeLabel(path.map((part) => part.name).join(" › "));
    setPickerOpen(false);
    setSearchInput("");
    setBrowsePath(path.slice(0, -1));
  }

  function selectSearchMatch(match: { node: NodeDTO; path: NodeDTO[] }) {
    const path = match.path.at(-1)?.id === match.node.id
      ? match.path
      : [...match.path, match.node];
    selectNode(match.node, path);
  }

  function retryCurrentBranch() {
    if (isStaleHierarchyCursorError(currentBranchQuery.error)) {
      void queryClient.resetQueries({ queryKey: currentBranchKey });
      return;
    }
    void currentBranchQuery.refetch();
  }

  function loadMoreCurrentBranch() {
    void currentBranchQuery.fetchNextPage();
  }

  function togglePicker() {
    if (pickerOpen) {
      setPickerOpen(false);
      return;
    }
    setSearchInput("");
    setPickerOpen(true);
    searchInputRef.current?.focus();
  }

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" data-testid="unit-calendar-page">
        <h2 className="text-xl font-semibold">{t("unit_calendar.title")}</h2>
        <div className="relative w-72 max-w-full">
          <label htmlFor="unit-calendar-node-search" className="mb-1 block text-xs text-gray-500 dark:text-gray-400">
            {t("unit_calendar.select_unit")}
          </label>
          <div className="flex gap-1">
            <input
              id="unit-calendar-node-search"
              ref={searchInputRef}
              type="search"
              role="combobox"
              aria-expanded={pickerOpen}
              aria-controls="unit-calendar-node-picker-options"
              aria-autocomplete="list"
              aria-activedescendant={activeOptionId}
              autoComplete="off"
              value={pickerOpen ? searchInput : selectedNodeLabel}
              placeholder={t("unit_calendar.all_units")}
              onFocus={() => {
                setPickerOpen(true);
                setSearchInput("");
              }}
              onChange={(event) => {
                setPickerOpen(true);
                setSearchInput(event.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setPickerOpen(false);
                  setSearchInput("");
                  return;
                }
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  setPickerOpen(true);
                  if (keyboardOptionCount > 0) {
                    setActiveIndex((index) => {
                      if (!pickerOpen) return 0;
                      const delta = event.key === "ArrowDown" ? 1 : -1;
                      return (index + delta + keyboardOptionCount) % keyboardOptionCount;
                    });
                  }
                  return;
                }
                if (event.key === "Enter" && pickerOpen && keyboardOptionCount > 0) {
                  event.preventDefault();
                  if (searching) {
                    const match = searchMatches[activeIndex];
                    if (match) selectSearchMatch(match);
                  } else {
                    const node = currentNodes[activeIndex];
                    if (node) selectNode(node, [...browsePath, node]);
                  }
                }
              }}
              className="block min-w-0 flex-1 rounded border p-1 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            />
            <button
              type="button"
              aria-label={pickerOpen ? t("unit_calendar.close_unit_picker") : t("unit_calendar.open_unit_picker")}
              onClick={togglePicker}
              className="rounded border px-2 text-sm dark:border-gray-600"
            >
              {pickerOpen ? "×" : "⌄"}
            </button>
          </div>
          {nodeId && (
            <button
              type="button"
              onClick={() => {
                setNodeId("");
                setSelectedNodeLabel("");
              }}
              className="mt-1 text-xs text-indigo-600 underline dark:text-indigo-300"
            >
              {t("unit_calendar.all_units")}
            </button>
          )}

          {pickerOpen && (
            <div
              id="unit-calendar-node-picker-options"
              className="absolute z-20 mt-1 max-h-80 w-full overflow-y-auto rounded border border-gray-200 bg-white p-2 shadow-lg dark:border-gray-600 dark:bg-gray-800"
              dir="auto"
            >
              {searching ? (
                <>
                  {searchMatches.length > 0 ? (
                    <ul role="listbox" aria-label={t("unit_calendar.search_results")} className="space-y-1">
                      {searchMatches.map((match, index) => {
                        const pathLabel = match.path.map((part) => part.name).join(" › ");
                        return (
                          <li key={match.node.id}>
                            <button
                              type="button"
                              id={`unit-calendar-node-option-${match.node.id}`}
                              role="option"
                              aria-selected={nodeId === match.node.id}
                              onClick={() => selectSearchMatch(match)}
                              className={`w-full rounded px-2 py-1 text-right text-sm hover:bg-gray-100 dark:hover:bg-gray-700 ${activeIndex === index ? "bg-indigo-50 outline outline-2 outline-indigo-400 dark:bg-indigo-950" : ""}`}
                            >
                              {pathLabel || match.node.name}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  ) : searchQuery.isPending || !searchIsCurrent ? (
                    <p className="p-2 text-sm text-gray-500">{t("unit_calendar.hierarchy_loading")}</p>
                  ) : searchQuery.isError ? (
                    <div className="p-2 text-sm text-red-600" role="alert">
                      <span>{t("unit_calendar.hierarchy_error")}</span>{" "}
                      <button type="button" onClick={() => void searchQuery.refetch()} className="underline">
                        {t("unit_calendar.retry")}
                      </button>
                    </div>
                  ) : (
                    <p className="p-2 text-sm text-gray-500">{t("unit_calendar.hierarchy_no_results")}</p>
                  )}
                  {searchIsCurrent && searchQuery.data?.has_more && (
                    <p className="p-2 text-xs text-gray-500">{t("unit_calendar.hierarchy_refine_search")}</p>
                  )}
                </>
              ) : (
                <>
                  <nav aria-label={t("unit_calendar.hierarchy_breadcrumbs")} className="mb-2 flex flex-wrap gap-1 text-xs">
                    <button type="button" onClick={() => setBrowsePath([])} className="underline">
                      {t("unit_calendar.hierarchy_roots")}
                    </button>
                    {browsePath.map((node, index) => (
                      <span key={node.id} className="flex items-center gap-1">
                        <span aria-hidden="true">›</span>
                        <button type="button" onClick={() => setBrowsePath(browsePath.slice(0, index + 1))} className="underline">
                          {node.name}
                        </button>
                      </span>
                    ))}
                  </nav>
                  {currentBranchQuery.isPending && currentNodes.length === 0 ? (
                    <p className="p-2 text-sm text-gray-500">{t("unit_calendar.hierarchy_loading")}</p>
                  ) : currentBranchQuery.isError && currentNodes.length === 0 ? (
                    <div className="p-2 text-sm text-red-600" role="alert">
                      <span>{t("unit_calendar.hierarchy_error")}</span>{" "}
                      <button type="button" onClick={retryCurrentBranch} className="underline">
                        {t("unit_calendar.retry")}
                      </button>
                    </div>
                  ) : currentNodes.length === 0 ? (
                    <p className="p-2 text-sm text-gray-500">{t("unit_calendar.hierarchy_empty")}</p>
                  ) : (
                    <ul role="listbox" aria-label={t("unit_calendar.hierarchy_nodes")} className="space-y-1">
                      {currentNodes.map((node, index) => (
                        <li key={node.id} className="flex items-center gap-1">
                          <button
                            type="button"
                            id={`unit-calendar-node-option-${node.id}`}
                            role="option"
                            aria-selected={effectiveNodeId === node.id}
                            onClick={() => selectNode(node, [...browsePath, node])}
                            className={`min-w-0 flex-1 truncate rounded px-2 py-1 text-right text-sm hover:bg-gray-100 dark:hover:bg-gray-700 ${effectiveNodeId === node.id ? "font-semibold text-indigo-600 dark:text-indigo-300" : ""} ${activeIndex === index ? "bg-indigo-50 outline outline-2 outline-indigo-400 dark:bg-indigo-950" : ""}`}
                          >
                            {node.name}
                          </button>
                          {node.has_children && (
                            <button
                              type="button"
                              aria-label={t("unit_calendar.hierarchy_open_children", { name: node.name })}
                              onClick={() => {
                                setBrowsePath([...browsePath, node]);
                                setSearchInput("");
                              }}
                              className="rounded px-2 py-1 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700"
                            >
                              ›
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {currentBranchQuery.isError && currentNodes.length > 0 && (
                    <div className="mt-2 text-sm text-red-600" role="alert">
                      <span>{t("unit_calendar.hierarchy_error")}</span>{" "}
                      <button type="button" onClick={retryCurrentBranch} className="underline">
                        {t("unit_calendar.retry")}
                      </button>
                    </div>
                  )}
                  {currentBranchQuery.hasNextPage && (
                    <button
                      type="button"
                      disabled={currentBranchQuery.isFetchingNextPage}
                      onClick={loadMoreCurrentBranch}
                      className="mt-2 w-full rounded border px-2 py-1 text-sm disabled:opacity-60 dark:border-gray-600"
                    >
                      {currentBranchQuery.isFetchingNextPage
                        ? t("unit_calendar.hierarchy_loading")
                        : t("unit_calendar.hierarchy_load_more")}
                    </button>
                  )}
                </>
              )}
            </div>
          )}
        </div>
        {effectiveNodeId ? (
          <UnitCalendar nodeId={effectiveNodeId} />
        ) : <p data-testid="unit-calendar-empty">{t("unit_calendar.none")}</p>}
      </section>
    </Layout>
  );
}
