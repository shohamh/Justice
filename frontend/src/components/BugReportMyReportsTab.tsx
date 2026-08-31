import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { queryKeys } from "../queryKeys";
import {
  getMyBugReports,
  markBugReportSeen,
  markAllMyBugReportsSeen,
  fetchMyBugReportScreenshot,
  BugReportSeverity,
  BugReportStatus,
} from "../api/bugReports";
import { translateApiError } from "../utils/translateApiError";
import BugReportCommentsPanel from "./BugReportCommentsPanel";
import DocumentPreviewModal from "./DocumentPreviewModal";

const SEVERITY_COLORS: Record<BugReportSeverity, string> = {
  low: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
  medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  high: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};

// Same intuitive open/in-progress/resolved/wont-fix palette as the admin
// bug reports table's STATUS_ROW_BG (BugReportsContent.tsx), just applied to
// a badge instead of a full row background.
const STATUS_COLORS: Record<BugReportStatus, string> = {
  open: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  in_progress: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  resolved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
  wont_fix: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
};

export interface BugReportMyReportsTabProps {
  expandedId: string | null;
  onToggle: (id: string | null) => void;
}

export default function BugReportMyReportsTab({ expandedId, onToggle }: BugReportMyReportsTabProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const query = useQuery({ queryKey: queryKeys.myBugReports(), queryFn: getMyBugReports });
  const reports = query.data?.items ?? [];

  const [screenshotUrlById, setScreenshotUrlById] = useState<Record<string, string>>({});
  const [screenshotErrorById, setScreenshotErrorById] = useState<Record<string, string>>({});
  const [previewImage, setPreviewImage] = useState<{ url: string; name: string } | null>(null);
  const [markingAllSeen, setMarkingAllSeen] = useState(false);
  const hasUnseenActivity = reports.some((r) => r.has_unseen_activity);

  async function handleMarkAllSeen() {
    setMarkingAllSeen(true);
    try {
      await markAllMyBugReportsSeen();
      await qc.invalidateQueries({ queryKey: queryKeys.myBugReports() });
      await qc.invalidateQueries({ queryKey: queryKeys.myBugReportsUnseenCount() });
    } finally {
      setMarkingAllSeen(false);
    }
  }

  // Keep a ref in sync so the unmount cleanup can revoke whatever URLs were
  // accumulated without re-registering the effect on every fetch.
  const screenshotUrlByIdRef = useRef(screenshotUrlById);
  screenshotUrlByIdRef.current = screenshotUrlById;

  useEffect(() => {
    return () => {
      Object.values(screenshotUrlByIdRef.current).forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  const bugReportSeverityLabel = (severity: BugReportSeverity) => t(`bug_reports.severity_${severity}`);
  const bugReportStatusLabel = (status: BugReportStatus) => t(`bug_reports.status_${status}`);

  async function loadScreenshot(id: string) {
    if (screenshotUrlByIdRef.current[id]) return;
    setScreenshotErrorById((prev) => ({ ...prev, [id]: "" }));
    try {
      const blob = await fetchMyBugReportScreenshot(id);
      setScreenshotUrlById((prev) => ({ ...prev, [id]: URL.createObjectURL(blob) }));
    } catch (err: unknown) {
      setScreenshotErrorById((prev) => ({
        ...prev,
        [id]: translateApiError(err, t, t("bug_reports.screenshot_load_error")),
      }));
    }
  }

  function handleToggle(reportId: string) {
    const collapsing = expandedId === reportId;
    onToggle(collapsing ? null : reportId);
  }

  useEffect(() => {
    if (!expandedId) return;
    // Fire-and-forget: marking a report "seen" clears its unread badge.
    // Failure here is non-fatal — the report simply stays flagged unread
    // until a future successful expand, which is an acceptable degrade.
    // Keyed on expandedId (not a click handler) so this fires both for a
    // manual expand AND for a report that arrives already expanded via the
    // `expandedId` prop (deep links from notifications / push / email —
    // see BugReportModalContext's `initialReportId`).
    void markBugReportSeen(expandedId)
      .then(() => {
        void qc.invalidateQueries({ queryKey: queryKeys.myBugReports() });
        void qc.invalidateQueries({ queryKey: queryKeys.myBugReportsUnseenCount() });
      })
      .catch(() => {});
  }, [expandedId, qc]);

  useEffect(() => {
    if (!expandedId) return;
    const report = reports.find((r) => r.id === expandedId);
    if (report?.has_screenshot) void loadScreenshot(expandedId);
    // Only re-runs when the expanded report changes or its has_screenshot
    // flag becomes known (reports load async) — loadScreenshot itself
    // guards against re-fetching an already-loaded screenshot, so a
    // `reports` reference change from an unrelated refetch is harmless.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedId, reports]);

  return (
    <div className="space-y-3">
      {hasUnseenActivity && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => { void handleMarkAllSeen(); }}
            disabled={markingAllSeen}
            className="text-xs px-2 py-1 rounded border dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
            data-testid="my-bug-reports-mark-all-seen"
          >
            {t("bug_reports.mark_all_seen")}
          </button>
        </div>
      )}
      {query.isLoading && (
        <p className="text-sm text-gray-500" data-testid="my-bug-reports-loading">{t("app.loading")}</p>
      )}
      {query.isError && (
        <p className="text-sm text-red-500" data-testid="my-bug-reports-error">
          {translateApiError(query.error, t, t("my_bug_reports.load_error"))}
        </p>
      )}
      {!query.isLoading && !query.isError && reports.length === 0 && (
        <p className="text-sm text-gray-500" data-testid="my-bug-reports-empty">{t("bug_reports.none")}</p>
      )}
      {!query.isLoading && !query.isError && reports.length > 0 && (
        <ul className="space-y-2 text-sm" data-testid="my-bug-reports-list">
          {reports.map((report) => {
            const isExpanded = expandedId === report.id;
            return (
              <li
                key={report.id}
                className="border dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800"
                data-testid={`my-bug-report-row-${report.id}`}
              >
                <button
                  type="button"
                  onClick={() => handleToggle(report.id)}
                  className="w-full flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 p-3 text-right"
                  aria-expanded={isExpanded}
                  data-testid={`my-bug-report-expand-${report.id}`}
                >
                  <div className="flex items-center flex-wrap gap-2 sm:contents">
                    <span dir="ltr" className="text-xs text-gray-500 dark:text-gray-400 shrink-0">
                      {new Date(report.created_at).toLocaleString("he-IL")}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded shrink-0 ${SEVERITY_COLORS[report.severity]}`}>
                      {bugReportSeverityLabel(report.severity)}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded shrink-0 ${STATUS_COLORS[report.status]}`}>
                      {bugReportStatusLabel(report.status)}
                    </span>
                    {report.has_unseen_activity && (
                      <span
                        className="w-2 h-2 rounded-full bg-red-500 shrink-0"
                        data-testid={`my-bug-report-unseen-${report.id}`}
                        aria-hidden="true"
                      />
                    )}
                  </div>
                  {!isExpanded && <span className="flex-1 min-w-0 whitespace-pre-wrap text-right">{report.description}</span>}
                  <div className="flex items-center justify-between sm:justify-start gap-2 shrink-0">
                    <span className="text-xs text-gray-500 dark:text-gray-400 shrink-0">
                      {report.comment_count} {t("bug_reports.comment_count")}
                    </span>
                    <span className="text-gray-400 shrink-0">{isExpanded ? "▲" : "▼"}</span>
                  </div>
                </button>
                {isExpanded && (
                  <div className="border-t dark:border-gray-600 p-3 space-y-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-gray-600 dark:text-gray-300">
                      <div><span className="font-medium">{t("bug_reports.report_route")}: </span>{report.route}</div>
                      <div><span className="font-medium">{t("bug_reports.report_created")}: </span>{new Date(report.created_at).toLocaleString("he-IL", { hour12: false })}</div>
                    </div>
                    <p className="whitespace-pre-wrap text-sm"><span className="font-medium">{t("bug_reports.description")}: </span>{report.description}</p>
                    {report.has_screenshot && screenshotUrlById[report.id] && (
                      <img
                        src={screenshotUrlById[report.id]}
                        alt={t("bug_reports.screenshot_alt")}
                        className="max-w-full sm:max-w-md rounded border dark:border-gray-600 cursor-zoom-in"
                        onClick={() =>
                          setPreviewImage({ url: screenshotUrlById[report.id], name: `bug-report-${report.id}.png` })
                        }
                        data-testid={`my-bug-report-screenshot-${report.id}`}
                      />
                    )}
                    {screenshotErrorById[report.id] && (
                      <p className="text-xs text-red-500" data-testid={`my-bug-report-screenshot-error-${report.id}`}>
                        {screenshotErrorById[report.id]}
                      </p>
                    )}
                    <BugReportCommentsPanel reportId={report.id} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {previewImage && (
        <DocumentPreviewModal
          fileUrl={previewImage.url}
          fileName={previewImage.name}
          contentType="image/png"
          onClose={() => setPreviewImage(null)}
        />
      )}
    </div>
  );
}
