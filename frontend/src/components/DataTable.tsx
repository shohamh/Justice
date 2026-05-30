import { useMemo, useState } from "react";
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
  cell: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number | null | undefined;
  filterValue?: (row: T) => string;
}

interface DataTableProps<T> {
  columns: ColDef<T>[];
  data: T[];
  filterPlaceholder?: string;
  className?: string;
  rowClassName?: (row: T) => string;
  emptyMessage?: string;
}

export function DataTable<T>({
  columns,
  data,
  filterPlaceholder = "סנן...",
  className,
  rowClassName,
  emptyMessage = "—",
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

  const tanCols: TanColumnDef<T>[] = useMemo(
    () =>
      columns.map((col) => ({
        id: col.id,
        header: col.header,
        cell: ({ row }) => col.cell(row.original),
        enableSorting: !!col.sortValue,
        enableGlobalFilter: !!col.filterValue,
        // accessorFn is required for TanStack to treat column as a data column (enables sorting/filtering)
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
    data,
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

  return (
    <div className={className}>
      <input
        value={globalFilter}
        onChange={(e) => setGlobalFilter(e.target.value)}
        placeholder={filterPlaceholder}
        className="mb-2 border rounded p-1 text-sm w-full sm:w-64"
      />
      <table className="w-full text-xs border-collapse">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="bg-gray-100 text-right">
              {hg.headers.map((header) => (
                <th
                  key={header.id}
                  className={`border px-2 py-1 whitespace-nowrap${header.column.getCanSort() ? " cursor-pointer select-none" : ""}`}
                  onClick={header.column.getToggleSortingHandler()}
                >
                  <span>{flexRender(header.column.columnDef.header, header.getContext())}</span>
                  {header.column.getIsSorted() === "asc" && <span aria-hidden> ▲</span>}
                  {header.column.getIsSorted() === "desc" && <span aria-hidden> ▼</span>}
                </th>
              ))}
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
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="border px-2 py-1">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
