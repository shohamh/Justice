import { api } from "./client";
import { downloadBlob } from "../utils/downloadFile";

export type ExportCell = string | number | boolean | null;

export interface WorksheetMatrix {
  sheet_name: string;
  headers: ExportCell[];
  rows: ExportCell[][];
}

export interface PlanningExportRequest {
  filename: string;
  tables: WorksheetMatrix[];
  config_sheets: string[];
  data_sheets: string[];
}

export async function exportTable(request: {
  filename: string;
  matrix: WorksheetMatrix;
}): Promise<void> {
  const response = await api.post<Blob>("/exports/xlsx", request, {
    responseType: "blob",
  });
  downloadBlob(response.data, request.filename);
}

export async function exportPlanning(request: PlanningExportRequest): Promise<void> {
  const response = await api.post<Blob>("/exports/planning-xlsx", request, {
    responseType: "blob",
  });
  downloadBlob(response.data, request.filename);
}
