import type { ReactNode } from "react";
import { DataTable, type ColDef } from "../DataTable"; import type { SortingState } from "@tanstack/react-table";

export interface PlanningColumn<T> {
  key: string;
  label: ReactNode;
  render: (row: T) => ReactNode;
  sortValue?: ColDef<T>["sortValue"];
  filterValue?: ColDef<T>["filterValue"];
  columnFilter?: ColDef<T>["columnFilter"];
  customColumnFilter?: ColDef<T>["customColumnFilter"];
  minWidth?: ColDef<T>["minWidth"];
  sortDescFirst?: ColDef<T>["sortDescFirst"];
  className?: string;
}

export interface PlanningTableProps<T> {
  columns: PlanningColumn<T>[];
  rows: T[];
  getRowId: (row: T) => string;
  getRowLabel?: (row: T) => string;
  onRowClick?: (row: T) => void;
  rowActions?: (row: T) => ReactNode;
  filters?: ReactNode;
  sort?: ReactNode;
  pagination?: ReactNode;
  loading?: boolean;
  error?: ReactNode;
  emptyMessage?: ReactNode;
  loadingMessage?: ReactNode;
  actionsLabel?: ReactNode;
  children?: ReactNode;
  filterPlaceholder?: string;
  rowClassName?: (row: T) => string;
  defaultSort?: SortingState;
}

export function PlanningTable<T>({
  columns,
  rows,
  getRowId,
  getRowLabel = () => "פתח שורה",
  onRowClick,
  rowActions,
  filters,
  sort,
  pagination,
  loading = false,
  error,
  emptyMessage = "אין נתונים",
  loadingMessage = "טוען...",
  actionsLabel = "פעולות",
  filterPlaceholder,
  rowClassName,
  defaultSort,
}: PlanningTableProps<T>) {
  const dataColumns: ColDef<T>[] = columns.map(column => ({
    id: column.key,
    header: typeof column.label === "string" ? column.label : String(column.label ?? ""),
    cell: column.render,
    sortValue: column.sortValue,
    filterValue: column.filterValue,
    columnFilter: column.columnFilter,
    customColumnFilter: column.customColumnFilter,
    minWidth: column.minWidth,
    sortDescFirst: column.sortDescFirst,
  }));
  if (rowActions) dataColumns.push({ id: "__actions", header: String(actionsLabel), cell: rowActions });

  if (loading) return <div className="space-y-3" dir="rtl"><div role="status" className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-500">{loadingMessage}</div></div>;
  if (error) return <div className="space-y-3" dir="rtl"><div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">{error}</div></div>;
  if (rows.length === 0) return <div className="space-y-3" dir="rtl"><div role="status" className="rounded-lg border border-dashed p-6 text-center text-sm text-gray-500">{emptyMessage}</div></div>;

  return (
    <div className="space-y-3" dir="rtl">
      {(filters || sort) && <div className="flex flex-wrap items-center justify-between gap-3">{filters}{sort}</div>}
      <DataTable
        columns={dataColumns}
        data={rows}
        emptyMessage={String(emptyMessage)}
        onRowClick={onRowClick}
        getRowLabel={getRowLabel}
        rowTestId={getRowId}
        filterPlaceholder={filterPlaceholder}
        rowClassName={rowClassName}
        defaultSort={defaultSort}
      />
      {pagination}
    </div>
  );
}

export default PlanningTable;
