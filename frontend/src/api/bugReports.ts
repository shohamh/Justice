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
  reporter_id: string | null;
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
  comment_count: number;
  last_comment_at: string | null;
  has_unseen_activity: boolean;
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

export async function getMyBugReports(): Promise<PaginatedBugReports> {
  return (await api.get<PaginatedBugReports>("/my/bug-reports")).data;
}

export interface BugReportUnseenCount {
  count: number;
}

export async function markBugReportSeen(reportId: string): Promise<void> {
  await api.post(`/bug-reports/${reportId}/seen`);
}

export async function getMyBugReportsUnseenCount(): Promise<BugReportUnseenCount> {
  return (await api.get<BugReportUnseenCount>("/my/bug-reports/unseen-count")).data;
}

export interface BugReportCommentAttachment {
  id: string;
  file_name: string;
  content_type: string;
}

export interface BugReportComment {
  id: string;
  bug_report_id: string;
  author_id: string;
  author_name: string;
  body: string;
  created_at: string;
  attachments: BugReportCommentAttachment[];
}

export async function listComments(reportId: string): Promise<BugReportComment[]> {
  return (await api.get<BugReportComment[]>(`/bug-reports/${reportId}/comments`)).data;
}

export async function createComment(reportId: string, body: string): Promise<BugReportComment> {
  return (await api.post<BugReportComment>(`/bug-reports/${reportId}/comments`, { body })).data;
}

export async function uploadCommentAttachment(
  reportId: string,
  commentId: string,
  file: File,
): Promise<BugReportCommentAttachment> {
  const formData = new FormData();
  formData.append("file", file);
  return (
    await api.post<BugReportCommentAttachment>(
      `/bug-reports/${reportId}/comments/${commentId}/attachments`,
      formData,
      { headers: { "Content-Type": "multipart/form-data" } },
    )
  ).data;
}

export function bugReportCommentAttachmentDownloadUrl(
  reportId: string,
  commentId: string,
  attachmentId: string,
): string {
  return `/bug-reports/${reportId}/comments/${commentId}/attachments/${attachmentId}`;
}
