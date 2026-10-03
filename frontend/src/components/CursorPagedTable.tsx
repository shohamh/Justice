import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type UIEvent,
} from "react";
import {
  useInfiniteQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef as TanColumnDef,
  type Row as TanRow,
  type SortingState,
} from "@tanstack/react-table";

import type { ColDef } from "./DataTable";

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
  meta?: unknown;
}

export interface CursorPageRequest {
  cursor?: string;
  search: string;
  sort: string;
  descending: boolean;
  roleOrder?: string[];
  pageSize: number;
  signal: AbortSignal;
}

export type CursorPageCriteria = Omit<CursorPageRequest, "cursor" | "signal">;

export interface CursorPagedTableLabels {
  searchLabel: string;
  searchPlaceholder: string;
  loading: string;
  loadingMore: string;
  loadMore: string;
  retry: string;
  loadFailed: string;
  emptyMessage: string;
  loaded: (count: number) => string;
  allLoaded: (count: number) => string;
  keyboardHint: string;
}

interface CursorPagedTableProps<T> {
  columns: ColDef<T>[];
  queryKey: QueryKey;
  scopeKey: unknown;
  filterKey?: unknown;
  roleOrder: string[];
  fetchPage: (request: CursorPageRequest) => Promise<CursorPage<T>>;
  isCursorStaleError?: (error: unknown) => boolean;
  getRowId: (row: T) => string;
  labels: CursorPagedTableLabels;
  testId?: string;
  tableLabel: string;
  pageSize?: number;
  enabled?: boolean;
  initialSort?: string;
  initialSortDescending?: boolean;
  onPageMeta?: (meta: unknown) => void;
  onCriteriaChange?: (criteria: CursorPageCriteria) => void;
  className?: string;
  rowTestId?: (row: T) => string;
  rowClassName?: (row: T) => string;
  rowStyle?: (row: T) => CSSProperties;
}

const ESTIMATED_ROW_HEIGHT = 56;
const OVERSCAN_ROWS = 8;
const PREFETCH_ROWS = 12;

function rowIndexAtOffset(offsets: number[], target: number): number {
  if (offsets.length <= 1) return 0;
  let low = 0;
  let high = offsets.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (offsets[middle] <= target) low = middle + 1;
    else high = middle;
  }
  return Math.max(0, Math.min(offsets.length - 2, low - 1));
}

export default function CursorPagedTable<T>({
  columns,
  queryKey,
  scopeKey,
  filterKey,
  roleOrder,
  fetchPage,
  isCursorStaleError,
  getRowId,
  labels,
  testId,
  tableLabel,
  pageSize = 100,
  enabled = true,
  initialSort = "full_name",
  initialSortDescending = false,
  onPageMeta,
  onCriteriaChange,
  className,
  rowTestId,
  rowClassName,
  rowStyle,
}: CursorPagedTableProps<T>) {
  const queryClient = useQueryClient();
  const queryKeyRef = useRef(queryKey);
  queryKeyRef.current = queryKey;
  const tableBodyId = useId();
  const searchInputId = useId();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([
    { id: initialSort, desc: initialSortDescending },
  ]);
  const [readyQueryGeneration, setReadyQueryGeneration] = useState<number | null>(
    null,
  );
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(480);
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  const [measurementVersion, setMeasurementVersion] = useState(0);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const measuredHeightsRef = useRef(new Map<string, number>());
  const rowObserversRef = useRef(new Map<string, ResizeObserver>());
  const rowRefCallbacksRef = useRef(
    new Map<string, (node: HTMLTableRowElement | null) => void>(),
  );
  const measurementFrameRef = useRef<number | null>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const nextPageInFlightRef = useRef(false);

  useEffect(() => {
    const timeout = window.setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => window.clearTimeout(timeout);
  }, [searchInput]);

  const sortState = sorting[0];
  const sort = sortState?.id ?? initialSort;
  const descending = sortState?.desc ?? false;
  const normalizedSearch = search.toLocaleLowerCase();
  const activeRoleOrder = sort === "role" || sort === "rank" ? roleOrder : undefined;
  const criteria = useMemo<CursorPageCriteria>(() => ({
    search: normalizedSearch,
    sort,
    descending,
    roleOrder: activeRoleOrder,
    pageSize,
  }), [normalizedSearch, sort, descending, activeRoleOrder, pageSize]);
  useEffect(() => {
    onCriteriaChange?.(criteria);
  }, [criteria, onCriteriaChange]);
  const resolvedQueryKey = useMemo(
    () => [
      ...queryKey,
      scopeKey,
      {
        search: normalizedSearch,
        sort,
        descending,
        roleOrder: activeRoleOrder ?? null,
        pageSize,
        filters: filterKey ?? null,
      },
    ],
    [
      queryKey,
      scopeKey,
      normalizedSearch,
      sort,
      descending,
      activeRoleOrder,
      pageSize,
      filterKey,
    ],
  );
  const queryIdentity = JSON.stringify(resolvedQueryKey);
  const queryIdentityGenerationRef = useRef({ queryIdentity, generation: 0 });
  if (queryIdentityGenerationRef.current.queryIdentity !== queryIdentity) {
    queryIdentityGenerationRef.current = {
      queryIdentity,
      generation: queryIdentityGenerationRef.current.generation + 1,
    };
  }
  const queryIdentityGeneration = queryIdentityGenerationRef.current.generation;
  const isQueryIdentityReady = readyQueryGeneration === queryIdentityGeneration;
  const resolvedQueryKeyRef = useRef(resolvedQueryKey);
  resolvedQueryKeyRef.current = resolvedQueryKey;
  const previousQueryRef = useRef({ queryIdentity, queryKey: resolvedQueryKey });
  useLayoutEffect(() => {
    const previous = previousQueryRef.current;
    if (!enabled) {
      void queryClient.cancelQueries({ queryKey: previous.queryKey, exact: true });
      if (previous.queryIdentity !== queryIdentity) {
        void queryClient.cancelQueries({ queryKey: resolvedQueryKey, exact: true });
      }
    }
    previousQueryRef.current = { queryIdentity, queryKey: resolvedQueryKey };
  }, [enabled, queryClient, queryIdentity, resolvedQueryKey]);
  const staleCursorRestartRef = useRef({ queryIdentity, restarted: false });
  if (staleCursorRestartRef.current.queryIdentity !== queryIdentity) {
    staleCursorRestartRef.current = { queryIdentity, restarted: false };
  }

  const query = useInfiniteQuery({
    queryKey: resolvedQueryKey,
    enabled: enabled && isQueryIdentityReady,
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) => {
      const page = await fetchPage({
        cursor: pageParam,
        search: normalizedSearch,
        sort,
        descending,
        roleOrder: activeRoleOrder,
        pageSize,
        signal,
      });
      if (
        pageParam === undefined &&
        staleCursorRestartRef.current.queryIdentity === queryIdentity &&
        staleCursorRestartRef.current.restarted
      ) {
        staleCursorRestartRef.current.restarted = false;
      }
      return page;
    },
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const firstPageMeta = enabled && isQueryIdentityReady
    ? query.data?.pages[0]?.meta
    : undefined;
  useEffect(() => {
    if (firstPageMeta !== undefined) onPageMeta?.(firstPageMeta);
  }, [firstPageMeta, onPageMeta]);
  useEffect(() => {
    let current = true;
    void queryClient
      .resetQueries({ queryKey: resolvedQueryKeyRef.current, exact: true })
      .then(() => {
        if (current) setReadyQueryGeneration(queryIdentityGeneration);
      });
    return () => {
      current = false;
    };
  }, [queryClient, queryIdentity, queryIdentityGeneration]);

  const queryData = enabled && isQueryIdentityReady ? query.data : undefined;
  const queryIsPending = !enabled || !isQueryIdentityReady || query.isPending;
  const queryHasError = enabled && isQueryIdentityReady && query.isError;
  const isFetchingNextPage =
    enabled && isQueryIdentityReady && query.isFetchingNextPage;
  const pageCount = queryData?.pages.length ?? 0;

  useEffect(() => {
    let lastResetAt = Number.NEGATIVE_INFINITY;
    const resetRoster = () => {
      if (document.visibilityState !== "visible") return;
      const now = Date.now();
      if (now - lastResetAt < 1_000) return;
      lastResetAt = now;
      void queryClient.resetQueries({
        queryKey: queryKeyRef.current,
        exact: false,
      });
    };

    window.addEventListener("focus", resetRoster);
    document.addEventListener("visibilitychange", resetRoster);
    return () => {
      window.removeEventListener("focus", resetRoster);
      document.removeEventListener("visibilitychange", resetRoster);
    };
  }, [queryClient]);

  const items = useMemo(() => {
    const unique = new Map<string, T>();
    for (const page of queryData?.pages ?? []) {
      for (const item of page.items) {
        const id = getRowId(item);
        if (!unique.has(id)) unique.set(id, item);
      }
    }
    return [...unique.values()];
  }, [queryData, getRowId]);

  const tableColumns = useMemo<TanColumnDef<T>[]>(
    () =>
      columns.map((column) => ({
        id: column.id,
        header: column.header as TanColumnDef<T>["header"],
        cell: ({ row }) => column.cell(row.original),
        enableSorting: Boolean(column.sortValue),
        sortDescFirst: column.sortDescFirst,
        accessorFn: column.sortValue
          ? (row: T) => column.sortValue?.(row) ?? ""
          : undefined,
      })),
    [columns],
  );

  const table = useReactTable({
    data: items,
    columns: tableColumns,
    state: { sorting },
    onSortingChange: setSorting,
    manualSorting: true,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => getRowId(row),
  });

  const hasMore = enabled && isQueryIdentityReady && (query.hasNextPage ?? false);
  const { fetchNextPage } = query;
  const loadNextPage = useCallback(async () => {
    if (
      !enabled ||
      !isQueryIdentityReady ||
      !hasMore ||
      isFetchingNextPage ||
      nextPageInFlightRef.current
    ) {
      return;
    }
    nextPageInFlightRef.current = true;
    try {
      let pageError: unknown;
      try {
        const result = await fetchNextPage({ cancelRefetch: false });
        if (result.isFetchNextPageError) pageError = result.error;
      } catch (error) {
        pageError = error;
      }
      const restartState = staleCursorRestartRef.current;
      if (
        pageError &&
        isCursorStaleError?.(pageError) &&
        restartState.queryIdentity === queryIdentity &&
        !restartState.restarted
      ) {
        restartState.restarted = true;
        await queryClient.resetQueries({ queryKey: resolvedQueryKey, exact: true });
      }
    } finally {
      nextPageInFlightRef.current = false;
    }
  }, [
    enabled,
    hasMore,
    isCursorStaleError,
    isQueryIdentityReady,
    fetchNextPage,
    isFetchingNextPage,
    queryClient,
    queryIdentity,
    resolvedQueryKey,
  ]);

  const layout = useMemo(() => {
    const offsets = new Array<number>(items.length + 1);
    offsets[0] = 0;
    for (let index = 0; index < items.length; index += 1) {
      const height = measuredHeightsRef.current.get(getRowId(items[index]));
      offsets[index + 1] = offsets[index] + (height ?? ESTIMATED_ROW_HEIGHT);
    }
    return offsets;
  // measurementVersion invalidates this layout after the ref-backed height map changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, getRowId, measurementVersion]);

  const totalHeight = layout[layout.length - 1] ?? 0;
  const firstVisibleIndex = items.length
    ? rowIndexAtOffset(
        layout,
        Math.max(0, scrollTop - OVERSCAN_ROWS * ESTIMATED_ROW_HEIGHT),
      )
    : 0;
  const lastVisibleIndex = items.length
    ? Math.min(
        items.length - 1,
        rowIndexAtOffset(
          layout,
          Math.min(
            totalHeight,
            scrollTop + viewportHeight + OVERSCAN_ROWS * ESTIMATED_ROW_HEIGHT,
          ),
        ) + 1,
      )
    : -1;
  const virtualEndIndex = lastVisibleIndex + 1;

  const renderedIndices = useMemo(() => {
    if (lastVisibleIndex < firstVisibleIndex) return [];
    const indices = Array.from(
      { length: lastVisibleIndex - firstVisibleIndex + 1 },
      (_, offset) => firstVisibleIndex + offset,
    );
    if (focusedRowId) {
      const focusedIndex = items.findIndex((item) => getRowId(item) === focusedRowId);
      if (focusedIndex >= 0 && !indices.includes(focusedIndex)) {
        indices.push(focusedIndex);
        indices.sort((a, b) => a - b);
      }
    }
    return indices;
  }, [firstVisibleIndex, lastVisibleIndex, focusedRowId, items, getRowId]);

  const getRowRef = useCallback((id: string) => {
    const cached = rowRefCallbacksRef.current.get(id);
    if (cached) return cached;
    const callback = (node: HTMLTableRowElement | null) => {
      rowObserversRef.current.get(id)?.disconnect();
      rowObserversRef.current.delete(id);
      if (!node || typeof ResizeObserver === "undefined") {
        if (!node) rowRefCallbacksRef.current.delete(id);
        return;
      }
      const observer = new ResizeObserver((entries) => {
        const height = entries[0]?.target.getBoundingClientRect().height;
        if (!height) return;
        const previousHeight = measuredHeightsRef.current.get(id);
        if (previousHeight !== undefined && Math.abs(previousHeight - height) < 1) return;
        measuredHeightsRef.current.set(id, height);
        if (measurementFrameRef.current !== null) return;
        measurementFrameRef.current = window.requestAnimationFrame(() => {
          measurementFrameRef.current = null;
          setMeasurementVersion((version) => version + 1);
        });
      });
      observer.observe(node);
      rowObserversRef.current.set(id, observer);
    };
    rowRefCallbacksRef.current.set(id, callback);
    return callback;
  }, []);

  useEffect(() => {
    measuredHeightsRef.current.clear();
    setMeasurementVersion((version) => version + 1);
    setFocusedRowId(null);
    setScrollTop(0);
    const container = scrollContainerRef.current;
    if (container) {
      if (typeof container.scrollTo === "function") container.scrollTo({ top: 0 });
      else container.scrollTop = 0;
    }
  }, [queryIdentity]);

  useEffect(() => {
    if (pageCount !== 0) return;
    measuredHeightsRef.current.clear();
    setMeasurementVersion((version) => version + 1);
    setFocusedRowId(null);
    setScrollTop(0);
    const container = scrollContainerRef.current;
    if (container) {
      if (typeof container.scrollTo === "function") container.scrollTo({ top: 0 });
      else container.scrollTop = 0;
    }
  }, [pageCount]);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const updateHeight = () => setViewportHeight(container.clientHeight);
    updateHeight();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateHeight);
      return () => window.removeEventListener("resize", updateHeight);
    }
    const observer = new ResizeObserver(updateHeight);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (
      enabled &&
      hasMore &&
      !queryHasError &&
      !isFetchingNextPage &&
      virtualEndIndex >= items.length - PREFETCH_ROWS
    ) {
      void loadNextPage();
    }
  }, [
    enabled,
    hasMore,
    queryHasError,
    isFetchingNextPage,
    virtualEndIndex,
    items.length,
    loadNextPage,
  ]);

  useEffect(
    () => () => {
      for (const observer of rowObserversRef.current.values()) observer.disconnect();
      if (measurementFrameRef.current !== null) {
        window.cancelAnimationFrame(measurementFrameRef.current);
      }
      if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current);
    },
    [],
  );

  function handleScroll(event: UIEvent<HTMLDivElement>) {
    const nextScrollTop = event.currentTarget.scrollTop;
    if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      setScrollTop(nextScrollTop);
    });
  }

  async function retryFailedPage() {
    if (!enabled || !isQueryIdentityReady) return;
    if (queryData?.pages.length) {
      await loadNextPage();
      return;
    }
    await query.refetch();
  }

  const statusText = queryIsPending
    ? labels.loading
    : isFetchingNextPage
      ? labels.loadingMore
      : queryHasError
        ? labels.loadFailed
        : hasMore
          ? labels.loaded(items.length)
          : labels.allLoaded(items.length);

  const headerGroups = table.getHeaderGroups();
  const columnCount = columns.length;
  const scrollHintId = useId();
  let previousRowEnd = 0;

  return (
    <div className={className} data-testid={testId}>
      <label className="sr-only" htmlFor={searchInputId}>
        {labels.searchLabel}
      </label>
      <input
        id={searchInputId}
        value={searchInput}
        onChange={(event) => setSearchInput(event.target.value)}
        placeholder={labels.searchPlaceholder}
        className="mb-2 border rounded p-1 text-sm w-full sm:w-64 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
        type="search"
        autoComplete="off"
      />
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {statusText}
      </p>
      {queryHasError && (
        <p className="mb-2 text-sm text-red-600" role="alert">
          {labels.loadFailed}
        </p>
      )}
      <p id={scrollHintId} className="mb-1 text-xs text-gray-500">
        {labels.keyboardHint}
      </p>
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="overflow-auto -mx-1 min-h-64 max-h-[70vh] focus:outline focus:outline-2 focus:outline-indigo-500"
        role="region"
        aria-label={tableLabel}
        aria-describedby={scrollHintId}
        tabIndex={0}
      >
        <table
          className="w-full text-xs border-collapse"
          aria-label={tableLabel}
          aria-rowcount={hasMore ? -1 : items.length + 1}
        >
          <thead className="sticky top-0 z-10">
            {headerGroups.map((headerGroup) => (
              <tr key={headerGroup.id} className="bg-gray-100 dark:bg-gray-700 text-right">
                {headerGroup.headers.map((header) => {
                  const column = columns.find((candidate) => candidate.id === header.id);
                  const sorted = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                      className="border dark:border-gray-600 px-2 py-1 whitespace-nowrap"
                      style={column?.minWidth ? { minWidth: column.minWidth } : undefined}
                    >
                      {header.column.getCanSort() ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 cursor-pointer select-none"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {sorted === "asc" && <span aria-hidden="true"> ▲</span>}
                          {sorted === "desc" && <span aria-hidden="true"> ▼</span>}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody id={tableBodyId}>
            {items.length === 0 ? (
              <tr>
                <td colSpan={columnCount} className="text-center text-gray-400 py-4">
                  {queryIsPending ? labels.loading : queryHasError ? labels.loadFailed : labels.emptyMessage}
                </td>
              </tr>
            ) : (
              renderedIndices.map((index) => {
                const row = table.getRowModel().rows[index];
                if (!row) return null;
                const rowId = getRowId(row.original);
                const gapHeight = layout[index] - layout[previousRowEnd];
                previousRowEnd = index + 1;
                return (
                  <FragmentRow
                    key={row.id}
                    row={row}
                    rowRef={getRowRef(rowId)}
                    rowIndex={index}
                    rowTestId={rowTestId}
                    rowClassName={rowClassName?.(row.original)}
                    rowStyle={rowStyle?.(row.original)}
                    gapHeight={gapHeight}
                    columnCount={columnCount}
                    onFocus={() => setFocusedRowId(rowId)}
                    onBlur={(event) => {
                      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                        setFocusedRowId((current) => (current === rowId ? null : current));
                      }
                    }}
                  />
                );
              })
            )}
            {items.length > 0 && totalHeight > layout[previousRowEnd] && (
              <tr aria-hidden="true" role="presentation">
                <td colSpan={columnCount} style={{ height: totalHeight - layout[previousRowEnd], padding: 0, border: 0 }} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {(hasMore || queryHasError) && (
        <button
          type="button"
          onClick={() => (queryHasError ? void retryFailedPage() : void loadNextPage())}
          disabled={query.isFetching}
          className="mt-2 rounded border border-gray-300 dark:border-gray-600 px-3 py-1 text-sm disabled:opacity-50"
          aria-controls={tableBodyId}
          data-testid="cursor-paged-table-load-more"
        >
          {queryHasError ? labels.retry : isFetchingNextPage ? labels.loadingMore : labels.loadMore}
        </button>
      )}
      {!hasMore && items.length > 0 && (
        <p className="mt-2 text-xs text-gray-500" aria-live="polite">
          {labels.allLoaded(items.length)}
        </p>
      )}
    </div>
  );
}

function FragmentRow<T>({
  row,
  rowRef,
  rowIndex,
  rowTestId,
  rowClassName,
  rowStyle,
  gapHeight,
  columnCount,
  onFocus,
  onBlur,
}: {
  row: TanRow<T>;
  rowRef: (node: HTMLTableRowElement | null) => void;
  rowIndex: number;
  rowTestId?: (row: T) => string;
  rowClassName?: string;
  rowStyle?: CSSProperties;
  gapHeight: number;
  columnCount: number;
  onFocus: () => void;
  onBlur: (event: FocusEvent<HTMLTableRowElement>) => void;
}) {
  return (
    <>
      {gapHeight > 0 && (
        <tr aria-hidden="true" role="presentation">
          <td colSpan={columnCount} style={{ height: gapHeight, padding: 0, border: 0 }} />
        </tr>
      )}
      <tr
        ref={rowRef}
        data-testid={rowTestId?.(row.original)}
        className={rowClassName}
        style={rowStyle}
        aria-rowindex={rowIndex + 2}
        onFocusCapture={onFocus}
        onBlurCapture={onBlur}
      >
        {row.getVisibleCells().map((cell) => (
          <td key={cell.id} className="border dark:border-gray-600 px-2 py-1">
            {flexRender(cell.column.columnDef.cell, cell.getContext())}
          </td>
        ))}
      </tr>
    </>
  );
}
