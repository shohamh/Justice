import { api } from "./client";
import type { NavHistoryEntry } from "../hooks/useNavigationHistory";

export type BugReportSeverity = "low" | "medium" | "high";
export type BugReportStatus = "open" | "in_progress" | "resolved" | "wont_fix";

export interface BugReportSubmitPayload {
  description: string;
  severity: BugReportSeverity;
  screenshot: string | null;
  route: string;
  nav_history: NavHistoryEntry[];
}

export async function submitBugReport(payload: BugReportSubmitPayload): Promise<void> {
  await api.post("/bug-reports", payload);
}

export interface BugReportSummary {
  id: string;
  reporter_id: string;
  description: string;
  severity: BugReportSeverity;
  status: BugReportStatus;
  route: string;
  nav_history: NavHistoryEntry[] | null;
  audit_snapshot: Record<string, unknown>[] | null;
  user_snapshot: Record<string, unknown> | null;
  has_screenshot: boolean;
  created_at: string;
  updated_at: string;
}

export interface PaginatedBugReports {
  items: BugReportSummary[];
  total: number;
}

export interface BugReportFilters {
  severity?: BugReportSeverity;
  status?: BugReportStatus;
  offset?: number;
  limit?: number;
}

export async function listBugReports(filters: BugReportFilters): Promise<PaginatedBugReports> {
  return (await api.get<PaginatedBugReports>("/admin/bug-reports", { params: filters })).data;
}

export async function getBugReportJson(id: string): Promise<unknown> {
  return (await api.get(`/admin/bug-reports/${id}/json`)).data;
}

export async function fetchBugReportScreenshot(id: string): Promise<Blob> {
  return (await api.get(`/admin/bug-reports/${id}/screenshot`, { responseType: "blob" })).data;
}

export async function updateBugReportStatus(id: string, status: BugReportStatus): Promise<BugReportSummary> {
  return (await api.patch<BugReportSummary>(`/admin/bug-reports/${id}`, { status })).data;
}

export interface BugReportImportFileResult {
  filename: string;
  status: "imported" | "already_exists" | "error";
  detail: string | null;
}

export interface BugReportImportSummary {
  results: BugReportImportFileResult[];
}

export async function importBugReports(files: File[]): Promise<BugReportImportSummary> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  return (
    await api.post<BugReportImportSummary>("/admin/bug-reports/import", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
  ).data;
}
