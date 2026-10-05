import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { exportTable } from "../api/exports";
import { ExcelExportButton } from "./ExcelExportButton";
import type { ColDef } from "./DataTable";

vi.mock("../api/exports", () => ({ exportTable: vi.fn() }));

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

beforeEach(() => {
  vi.mocked(exportTable).mockReset();
  vi.mocked(exportTable).mockResolvedValue(undefined);
});

test("is disabled when there are no rows", () => {
  render(<ExcelExportButton columns={columns} rows={[]} filename="x.xlsx" />);
  expect(screen.getByRole("button")).toBeDisabled();
});

test("is enabled when there are rows", () => {
  render(<ExcelExportButton columns={columns} rows={rows} filename="x.xlsx" />);
  expect(screen.getByRole("button")).not.toBeDisabled();
});

test("sends localized headers and visible rows with the export value fallback chain", async () => {
  render(<ExcelExportButton columns={columns} rows={rows} filename="export.xlsx" />);
  fireEvent.click(screen.getByRole("button"));

  await waitFor(() => {
    expect(exportTable).toHaveBeenCalledWith({
      filename: "export.xlsx",
      matrix: {
        sheet_name: "Sheet1",
        headers: ["שם", "ניקוד", "תווית"],
        rows: [
          ["Alice", 3, "3 out of 10"],
          ["Bob", 7, "7 out of 10"],
        ],
      },
    });
  });
});

test("sends the rows returned by onBeforeExport", async () => {
  const preparedRows = [{ name: "Prepared", score: 11 }];
  const onBeforeExport = vi.fn().mockResolvedValue(preparedRows);
  render(<ExcelExportButton columns={columns} rows={rows} filename="prepared.xlsx" onBeforeExport={onBeforeExport} />);
  fireEvent.click(screen.getByRole("button"));

  await waitFor(() => {
    expect(exportTable).toHaveBeenCalledWith({
      filename: "prepared.xlsx",
      matrix: {
        sheet_name: "Sheet1",
        headers: ["שם", "ניקוד", "תווית"],
        rows: [["Prepared", 11, "11 out of 10"]],
      },
    });
  });
});

test("disables the button while the export request is pending", async () => {
  let finishExport = () => {};
  vi.mocked(exportTable).mockReturnValue(new Promise<void>((resolve) => {
    finishExport = resolve;
  }));
  render(<ExcelExportButton columns={columns} rows={rows} filename="export.xlsx" />);
  const button = screen.getByRole("button");
  fireEvent.click(button);

  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("aria-busy", "true");

  finishExport();
  await waitFor(() => expect(button).not.toBeDisabled());
  expect(button).toHaveAttribute("aria-busy", "false");
});

test("reports export request errors through onExportError", async () => {
  const error = new Error("Export failed");
  const onExportError = vi.fn();
  vi.mocked(exportTable).mockRejectedValue(error);
  render(<ExcelExportButton columns={columns} rows={rows} filename="export.xlsx" onExportError={onExportError} />);
  fireEvent.click(screen.getByRole("button"));

  await waitFor(() => expect(onExportError).toHaveBeenCalledWith(error));
});
