import { render, screen, fireEvent } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import * as XLSX from "xlsx";
import { ExcelExportButton } from "./ExcelExportButton";
import type { ColDef } from "./DataTable";

interface Row { name: string; score: number; }

const columns: ColDef<Row>[] = [
  { id: "name", header: "שם", cell: (r) => r.name, filterValue: (r) => r.name },
  { id: "score", header: "ניקוד", cell: (r) => String(r.score), sortValue: (r) => r.score },
  {
    id: "label",
    header: "תווית",
    cell: (r) => `${r.score}/10`,
    sortValue: (r) => r.score,
    exportValue: (r) => `${r.score} out of 10`,
  },
];

const rows: Row[] = [
  { name: "Alice", score: 3 },
  { name: "Bob", score: 7 },
];

test("is disabled when there are no rows", () => {
  render(<ExcelExportButton columns={columns} rows={[]} filename="x.xlsx" />);
  expect(screen.getByRole("button")).toBeDisabled();
});

test("is enabled when there are rows", () => {
  render(<ExcelExportButton columns={columns} rows={rows} filename="x.xlsx" />);
  expect(screen.getByRole("button")).not.toBeDisabled();
});

test("writes a workbook with header row and exportValue fallback chain on click", () => {
  const writeFileSpy = vi.spyOn(XLSX, "writeFile").mockImplementation(() => {});
  render(<ExcelExportButton columns={columns} rows={rows} filename="export.xlsx" />);
  fireEvent.click(screen.getByRole("button"));

  expect(writeFileSpy).toHaveBeenCalledTimes(1);
  const [wb, filename] = writeFileSpy.mock.calls[0];
  expect(filename).toBe("export.xlsx");
  const ws = wb.Sheets[wb.SheetNames[0]];
  const aoa = XLSX.utils.sheet_to_json(ws, { header: 1 }) as unknown[][];
  expect(aoa[0]).toEqual(["שם", "ניקוד", "תווית"]);
  // row for Alice: name via filterValue, score via sortValue, label via exportValue
  expect(aoa[1]).toEqual(["Alice", 3, "3 out of 10"]);
  expect(aoa[2]).toEqual(["Bob", 7, "7 out of 10"]);

  writeFileSpy.mockRestore();
});
