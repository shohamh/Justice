import { useMemo, useState, useRef, useEffect } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef as TanColumnDef,
  type SortingState,
} from "@tanstack/react-table";

export interface ColDef<T> {
  id: string;
  header: string;
  headerTooltip?: React.ReactNode;
  cell: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number | null | undefined;
  filterValue?: (row: T) => string;
  /** When true, shows an Excel-style dropdown with checkboxes for unique values in this column. */
  columnFilter?: boolean;
  /** Minimum column width in pixels. */
  minWidth?: number;
  /** Plain value for Excel export. Falls back to filterValue, then sortValue, then "". */
  exportValue?: (row: T) => string | number | boolean | null | undefined;
}

interface DataTableProps<T> {
  columns: ColDef<T>[];
  data: T[];
  filterPlaceholder?: string;
  className?: string;
  rowClassName?: (row: T) => string;
  rowStyle?: (row: T) => React.CSSProperties;
  emptyMessage?: string;
  testId?: string;
  rowTestId?: (row: T) => string;
  /** Fires with the fully filtered + sorted row set whenever it changes (e.g. for export). */
  onVisibleRowsChange?: (rows: T[]) => void;
}

// ─── Column filter dropdown ───────────────────────────────────────────────────

function ColumnFilterDropdown<T>({
  col,
  data,
  selected,
  onChange,
}: {
  col: ColDef<T>;
  data: T[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const uniqueValues = useMemo(() => {
    const vals = new Set<string>();
    for (const row of data) {
      const v = col.filterValue ? col.filterValue(row) : col.sortValue ? String(col.sortValue(row) ?? "") : "";
      if (v) vals.add(v);
    }
    return [...vals].sort((a, b) => a.localeCompare(b, "he"));
  }, [data, col]);

  const isFiltered = selected.size > 0 && selected.size < uniqueValues.length;
  const allSelected = selected.size === 0 || selected.size === uniqueValues.length;

  function toggleAll() {
    onChange(new Set()); // empty = all
  }

  function toggle(val: string) {
    const next = new Set(selected.size === 0 ? uniqueValues : [...selected]);
    if (next.has(val)) {
      next.delete(val);
      if (next.size === uniqueValues.length) onChange(new Set()); // back to "all"
      else onChange(next);
    } else {
      next.add(val);
      if (next.size === uniqueValues.length) onChange(new Set());
      else onChange(next);
    }
  }

  function isChecked(val: string) {
    return selected.size === 0 || selected.has(val);
  }

  return (
    <div ref={ref} className="relative inline-block" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        title="סנן עמודה"
        onClick={() => setOpen((o) => !o)}
        className={`ml-1 text-[10px] border rounded px-0.5 leading-none transition-colors ${
          isFiltered
            ? "border-indigo-500 text-indigo-600 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-900"
            : "border-gray-300 text-gray-400 hover:text-gray-600 dark:border-gray-500 dark:text-gray-500 dark:hover:text-gray-300"
        }`}
      >
        {isFiltered ? "▼●" : "▼"}
      </button>

      {open && (
        <div className="absolute top-full mt-1 z-30 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg shadow-xl min-w-32 max-h-56 flex flex-col"
          style={{ right: 0 }}
          dir="rtl"
        >
          {/* Select all */}
          <label className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer border-b border-gray-100 dark:border-gray-700 text-xs font-medium text-gray-700 dark:text-gray-200">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              className="accent-indigo-600"
            />
            הכל
          </label>
          {/* Values list */}
          <div className="overflow-y-auto">
            {uniqueValues.map((val) => (
              <label
                key={val}
                className="flex items-center gap-2 px-3 py-1 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer text-xs text-gray-700 dark:text-gray-300"
              >
                <input
                  type="checkbox"
                  checked={isChecked(val)}
                  onChange={() => toggle(val)}
                  className="accent-indigo-600"
                />
                {val}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main DataTable ───────────────────────────────────────────────────────────

export function DataTable<T>({
  columns,
  data,
  filterPlaceholder = "סנן...",
  className,
  rowClassName,
  rowStyle,
  emptyMessage = "—",
  testId,
  rowTestId,
  onVisibleRowsChange,
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [tooltipModal, setTooltipModal] = useState<React.ReactNode | null>(null);
  // colId → selected values (empty Set = all / no filter)
  const [colFilters, setColFilters] = useState<Record<string, Set<string>>>({});

  // Keep a ref to latest columns so filteredData can read them without
  // listing columns in its deps (columns reference changes every parent render
  // even when content is identical, which would trigger an infinite update loop
  // via onVisibleRowsChange → parent setState → re-render → new columns ref).
  const columnsRef = useRef(columns);
  columnsRef.current = columns;

  // Apply column-level filters on top of global filter
  const filteredData = useMemo(() => {
    return data.filter((row) => {
      for (const col of columnsRef.current) {
        if (!col.columnFilter) continue;
        const selected = colFilters[col.id];
        if (!selected || selected.size === 0) continue;
        const val = col.filterValue ? col.filterValue(row) : col.sortValue ? String(col.sortValue(row) ?? "") : "";
        if (!selected.has(val)) return false;
      }
      return true;
    });
  }, [data, colFilters]);

  const tanCols: TanColumnDef<T>[] = useMemo(
    () =>
      columns.map((col) => ({
        id: col.id,
        header: col.header,
        meta: { tooltip: col.headerTooltip } as { tooltip?: React.ReactNode },
        cell: ({ row }) => col.cell(row.original),
        enableSorting: !!col.sortValue,
        enableGlobalFilter: !!col.filterValue,
        accessorFn: col.filterValue
          ? (row: T) => col.filterValue!(row)
          : col.sortValue
          ? (row: T) => col.sortValue!(row) ?? ""
          : undefined,
        sortingFn: col.sortValue
          ? (rowA, rowB) => {
              const a = col.sortValue!(rowA.original) ?? null;
              const b = col.sortValue!(rowB.original) ?? null;
              if (a === null && b === null) return 0;
              if (a === null) return 1;
              if (b === null) return -1;
              if (typeof a === "string" && typeof b === "string")
                return a.localeCompare(b, "he");
              return (a as number) < (b as number) ? -1 : (a as number) > (b as number) ? 1 : 0;
            }
          : "auto",
      })),
    [columns]
  );

  const table = useReactTable({
    data: filteredData,
    columns: tanCols,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    sortDescFirst: false,
    globalFilterFn: (row, columnId, value: string) => {
      const cellValue = row.getValue(columnId);
      if (typeof cellValue !== "string") return false;
      return cellValue.toLowerCase().includes(value.toLowerCase());
    },
  });

  // Memoize by the state that actually affects which rows are visible:
  // data + column filters + global filter + sort. Excludes `columns` and
  // `tableRows` references which change on every parent render even when
  // the actual visible rows are unchanged.
  const visibleRows = useMemo(
    () => table.getRowModel().rows.map((r) => r.original),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, colFilters, globalFilter, sorting],
  );
  useEffect(() => {
    onVisibleRowsChange?.(visibleRows);
  }, [visibleRows, onVisibleRowsChange]);

  return (
    <div className={className} data-testid={testId}>
      <input
        value={globalFilter}
        onChange={(e) => setGlobalFilter(e.target.value)}
        placeholder={filterPlaceholder}
        className="mb-2 border rounded p-1 text-sm w-full sm:w-64 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
      />
      <div className="overflow-x-auto -mx-1">
      <table className="w-full text-xs border-collapse">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="bg-gray-100 dark:bg-gray-700 text-right">
              {hg.headers.map((header) => {
                const colDef = columns.find((c) => c.id === header.id);
                return (
                  <th
                    key={header.id}
                    className={`border dark:border-gray-600 px-2 py-1 whitespace-nowrap${header.column.getCanSort() ? " cursor-pointer select-none" : ""}`}
                    style={colDef?.minWidth ? { minWidth: colDef.minWidth } : undefined}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    <span className="inline-flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {(header.column.columnDef.meta as { tooltip?: React.ReactNode })?.tooltip && (
                        <button
                          type="button"
                          onClick={() => setTooltipModal((header.column.columnDef.meta as { tooltip?: React.ReactNode }).tooltip!)}
                          className="text-gray-400 hover:text-gray-600 text-xs border border-gray-300 rounded-full w-3.5 h-3.5 inline-flex items-center justify-center cursor-pointer"
                        >
                          ?
                        </button>
                      )}
                      {colDef?.columnFilter && (
                        <ColumnFilterDropdown
                          col={colDef}
                          data={data}
                          selected={colFilters[colDef.id] ?? new Set()}
                          onChange={(next) =>
                            setColFilters((prev) => ({ ...prev, [colDef.id]: next }))
                          }
                        />
                      )}
                    </span>
                    {header.column.getIsSorted() === "asc" && <span aria-hidden> ▲</span>}
                    {header.column.getIsSorted() === "desc" && <span aria-hidden> ▼</span>}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="text-center text-gray-400 py-4">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className={rowClassName ? rowClassName(row.original) : undefined}
                style={rowStyle ? rowStyle(row.original) : undefined}
                data-testid={rowTestId ? rowTestId(row.original) : undefined}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="border dark:border-gray-600 px-2 py-1">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
      </div>

      {tooltipModal && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setTooltipModal(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md mx-4" dir="rtl" onClick={(e) => e.stopPropagation()}>
            <div className="text-sm">{tooltipModal}</div>
            <div className="mt-4 text-left">
              <button type="button" className="bg-indigo-600 text-white px-3 py-1 rounded text-sm" onClick={() => setTooltipModal(null)}>סגור</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
