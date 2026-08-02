import type { ReactNode } from "react";

export interface PlanningColumn<T> {
  key: string;
  label: ReactNode;
  render: (row: T) => ReactNode;
  sortable?: boolean;
  onSort?: () => void;
  className?: string;
}

export interface PlanningTableProps<T> {
  columns: PlanningColumn<T>[];
  rows: T[];
  getRowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  rowActions?: (row: T) => ReactNode;
  filters?: ReactNode;
  sort?: ReactNode;
  pagination?: ReactNode;
  loading?: boolean;
  error?: ReactNode;
  emptyMessage?: ReactNode;
}

export function PlanningTable<T>({
  columns,
  rows,
  getRowId,
  onRowClick,
  rowActions,
  filters,
  sort,
  pagination,
  loading = false,
  error,
  emptyMessage = "Nothing here",
}: PlanningTableProps<T>) {
  const hasActionColumn = Boolean(rowActions);

  return (
    <div className="space-y-3" dir="rtl">
      {(filters || sort) && <div className="flex flex-wrap items-center justify-between gap-3">{filters}{sort}</div>}
      {loading ? (
        <div role="status" className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-500">Loading</div>
      ) : error ? (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">{error}</div>
      ) : rows.length === 0 ? (
        <div role="status" className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-500">{emptyMessage}</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-700">
              <tr>
                {columns.map(column => (
                  <th key={column.key} scope="col" className={`whitespace-nowrap px-3 py-2 text-right font-medium ${column.className ?? ""}`}>
                    {column.sortable && column.onSort ? (
                      <button type="button" className="hover:underline" onClick={column.onSort}>{column.label}</button>
                    ) : column.label}
                  </th>
                ))}
                {hasActionColumn && <th scope="col" className="px-3 py-2 text-right font-medium">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr
                  key={getRowId(row)}
                  className={`border-t border-gray-200 dark:border-gray-600 ${onRowClick ? "cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700" : ""}`}
                  onClick={() => onRowClick?.(row)}
                >
                  {columns.map(column => <td key={column.key} className={`px-3 py-2 ${column.className ?? ""}`}>{column.render(row)}</td>)}
                  {hasActionColumn && <td className="px-3 py-2" onClick={event => event.stopPropagation()}>{rowActions?.(row)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pagination}
    </div>
  );
}

export default PlanningTable;
