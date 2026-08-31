import { api } from "./client";
import type { NavHistoryEntry } from "../hooks/useNavigationHistory";
import { isRecord, optionalArrayResponse, requiredArrayResponse, requiredObjectResponse } from "./responseGuards";

export type BugReportSeverity = "low" | "medium" | "high";
export type BugReportStatus = "open" | "in_progress" | "resolved" | "wont_fix";
export type ActiveBugReportStatus = Extract<BugReportStatus, "open" | "in_progress">;

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
  unread: boolean;
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

/**
 * Normalizes one raw bug-report summary row: drops it if the row itself
 * isn't an object, otherwise coerces the nested `nav_history` and
 * `audit_snapshot` arrays so BugReportsContent's `(report.x ?? []).map`
 * calls can't throw on a malformed (but truthy, non-array) value and take
 * the whole reports table down.
 */
function sanitizeBugReportSummary(raw: unknown): BugReportSummary | null {
  if (!isRecord(raw)) return null;
  return {
    ...(raw as unknown as BugReportSummary),
    nav_history: raw.nav_history == null ? null : optionalArrayResponse<NavHistoryEntry>(raw.nav_history),
    audit_snapshot:
      raw.audit_snapshot == null ? null : optionalArrayResponse<Record<string, unknown>>(raw.audit_snapshot),
  };
}

export async function listBugReports(filters: BugReportFilters): Promise<PaginatedBugReports> {
  const r = await api.get<unknown>("/admin/bug-reports", { params: filters });
  const data = requiredObjectResponse(r.data, "Invalid bug reports response");
  return {
    ...(data as unknown as PaginatedBugReports),
    items: optionalArrayResponse<unknown>(data.items)
      .map(sanitizeBugReportSummary)
      .filter((item): item is BugReportSummary => item !== null),
  };
}

export interface ErrorLogEntry {
  source: "backend" | "frontend";
  timestamp: string | null;
  level: string;
  message: string;
  request_id: string | null;
  details: Record<string, unknown>;
  record_key: string;
  unread: boolean;
}

export interface PaginatedErrorLogs {
  items: ErrorLogEntry[];
  total: number;
}

export async function listAdminErrors(options: {
  source?: "backend" | "frontend";
  offset?: number;
  limit?: number;
  from?: string;
  to?: string;
} = {}): Promise<PaginatedErrorLogs> {
  const r = await api.get<unknown>("/admin/errors", { params: options });
  const data = requiredObjectResponse(r.data, "Invalid admin errors response");
  return {
    ...(data as unknown as PaginatedErrorLogs),
    items: optionalArrayResponse<ErrorLogEntry>(data.items),
  };
}

export async function getAdminErrorUnreadCount(): Promise<number> {
  return (await api.get<{ count: number }>("/admin/errors/unread-count")).data.count;
}

export async function markAdminErrorsRead(entries: Array<{ record_key: string; source: "backend" | "frontend" }>): Promise<void> {
  await api.post("/admin/errors/mark-read", { entries });
}

export async function markAllAdminErrorsRead(options: { source?: "backend" | "frontend"; from?: string; to?: string } = {}): Promise<void> {
  await api.post("/admin/errors/mark-all-read", undefined, { params: options });
}

export async function clearAdminErrors(through: string): Promise<number> {
  return (await api.delete<{ removed: number }>("/admin/errors", { params: { through } })).data.removed;
}

export async function getAdminBugReportUnreadCount(): Promise<number> {
  return (await api.get<{ count: number }>("/admin/bug-reports/unread-count")).data.count;
}

export async function markAdminBugReportsRead(reportIds: string[]): Promise<void> {
  await api.post("/admin/bug-reports/mark-read", { report_ids: reportIds });
}

export async function markAllAdminBugReportsRead(options: { severity?: BugReportSeverity; status?: BugReportStatus } = {}): Promise<void> {
  await api.post("/admin/bug-reports/mark-all-read", undefined, { params: options });
}

export interface DownloadBugReportExportOptions {
  scope?: "all_active" | "filtered";
  severity?: BugReportSeverity;
  status?: BugReportStatus;
}

export interface BugReportExportDownload {
  blob: Blob;
  filename: string | null;
}

function isActiveBugReportStatus(status: BugReportStatus | undefined): status is ActiveBugReportStatus {
  return status === "open" || status === "in_progress";
}

function parseDownloadFilename(contentDisposition: string | undefined): string | null {
  if (!contentDisposition) return null;

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) return decodeURIComponent(utf8Match[1]);

  const quotedMatch = contentDisposition.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) return quotedMatch[1];

  const plainMatch = contentDisposition.match(/filename=([^;]+)/i);
  return plainMatch?.[1]?.trim() ?? null;
}

export async function downloadBugReportExport(
  options: DownloadBugReportExportOptions = {},
): Promise<BugReportExportDownload> {
  const scope = options.scope ?? "all_active";
  const params: Record<string, string> = { scope };

  if (scope === "filtered") {
    if (options.severity) params.severity = options.severity;
    if (isActiveBugReportStatus(options.status)) params.status = options.status;
  }

  const response = await api.get<Blob>("/admin/bug-reports/export", {
    params,
    responseType: "blob",
  });

  return {
    blob: response.data,
    filename: parseDownloadFilename(response.headers["content-disposition"] as string | undefined),
  };
}

export async function getBugReportJson(id: string): Promise<unknown> {
  return (await api.get(`/admin/bug-reports/${id}/json`)).data;
}

export async function fetchBugReportScreenshot(id: string): Promise<Blob> {
  return (await api.get(`/admin/bug-reports/${id}/screenshot`, { responseType: "blob" })).data;
}

export async function fetchMyBugReportScreenshot(id: string): Promise<Blob> {
  return (await api.get(`/bug-reports/${id}/screenshot`, { responseType: "blob" })).data;
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

/**
 * Normalizes one raw comment row: drops it if the row itself isn't an
 * object, otherwise coerces the nested `attachments` array so
 * BugReportCommentsPanel's `.map` over a comment's attachments can't throw
 * and take the whole comment thread down.
 */
function sanitizeBugReportComment(raw: unknown): BugReportComment | null {
  if (!isRecord(raw)) return null;
  return {
    ...(raw as unknown as BugReportComment),
    attachments: optionalArrayResponse<BugReportCommentAttachment>(raw.attachments),
  };
}

export async function listComments(reportId: string): Promise<BugReportComment[]> {
  const r = await api.get<unknown>(`/bug-reports/${reportId}/comments`);
  const arr = requiredArrayResponse<unknown>(r.data, "Invalid bug report comments response");
  return arr.map(sanitizeBugReportComment).filter((c): c is BugReportComment => c !== null);
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
