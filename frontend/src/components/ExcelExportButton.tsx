import { FileSpreadsheet } from "lucide-react";
import * as XLSX from "xlsx";
import type { ColDef } from "./DataTable";

interface ExcelExportButtonProps<T> {
  columns: ColDef<T>[];
  rows: T[];
  filename: string;
}

export function exportValueOf<T>(col: ColDef<T>, row: T): string | number | boolean {
  const value = col.exportValue
    ? col.exportValue(row)
    : col.filterValue
      ? col.filterValue(row)
      : col.sortValue
        ? col.sortValue(row)
        : undefined;
  return value ?? "";
}

export function ExcelExportButton<T>({ columns, rows, filename }: ExcelExportButtonProps<T>) {
  function handleExport() {
    const header = columns.map((c) => c.header);
    const body = rows.map((row) => columns.map((c) => exportValueOf(c, row)));
    const ws = XLSX.utils.aoa_to_sheet([header, ...body]);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
    XLSX.writeFile(wb, filename);
  }

  return (
    <button
      type="button"
      disabled={rows.length === 0}
      onClick={handleExport}
      className="text-sm text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700 px-3 py-1 rounded hover:bg-green-50 dark:hover:bg-green-950 flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
    >
      <FileSpreadsheet className="w-4 h-4" />
      ייצוא לאקסל
    </button>
  );
}
