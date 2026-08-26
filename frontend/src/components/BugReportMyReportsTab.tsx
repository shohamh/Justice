import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { queryKeys } from "../queryKeys";
import { getMyBugReports, markBugReportSeen, BugReportSeverity, BugReportStatus } from "../api/bugReports";
import { translateApiError } from "../utils/translateApiError";
import BugReportCommentsPanel from "./BugReportCommentsPanel";

const SEVERITY_COLORS: Record<BugReportSeverity, string> = {
  low: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
  medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  high: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
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

  const bugReportSeverityLabel = (severity: BugReportSeverity) => t(`bug_reports.severity_${severity}`);
  const bugReportStatusLabel = (status: BugReportStatus) => t(`bug_reports.status_${status}`);

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

  return (
    <div className="space-y-3">
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
                  className="w-full flex items-center gap-3 p-3 text-right"
                  aria-expanded={isExpanded}
                  data-testid={`my-bug-report-expand-${report.id}`}
                >
                  <span dir="ltr" className="text-xs text-gray-500 dark:text-gray-400 shrink-0">
                    {new Date(report.created_at).toLocaleString("he-IL")}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded shrink-0 ${SEVERITY_COLORS[report.severity]}`}>
                    {bugReportSeverityLabel(report.severity)}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 shrink-0">
                    {bugReportStatusLabel(report.status)}
                  </span>
                  <span className="flex-1 min-w-0 whitespace-pre-wrap text-right">{report.description}</span>
                  {report.has_unseen_activity && (
                    <span
                      className="w-2 h-2 rounded-full bg-red-500 shrink-0"
                      data-testid={`my-bug-report-unseen-${report.id}`}
                      aria-hidden="true"
                    />
                  )}
                  <span className="text-xs text-gray-500 dark:text-gray-400 shrink-0">
                    {report.comment_count} {t("bug_reports.comment_count")}
                  </span>
                  <span className="text-gray-400 shrink-0">{isExpanded ? "▲" : "▼"}</span>
                </button>
                {isExpanded && (
                  <div className="border-t dark:border-gray-600 p-3 space-y-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-gray-600 dark:text-gray-300">
                      <div><span className="font-medium">{t("bug_reports.report_route")}: </span>{report.route}</div>
                      <div><span className="font-medium">{t("bug_reports.report_created")}: </span>{new Date(report.created_at).toLocaleString("he-IL", { hour12: false })}</div>
                    </div>
                    <p className="whitespace-pre-wrap text-sm"><span className="font-medium">{t("bug_reports.description")}: </span>{report.description}</p>
                    <BugReportCommentsPanel reportId={report.id} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
