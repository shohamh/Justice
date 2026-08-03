import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import { getMyBugReports, BugReportSeverity, BugReportStatus } from "../api/bugReports";
import { translateApiError } from "../utils/translateApiError";
import BugReportCommentsPanel from "../components/BugReportCommentsPanel";

const SEVERITY_COLORS: Record<BugReportSeverity, string> = {
  low: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
  medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  high: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};

export default function MyBugReportsPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  // Notification deep-links arrive as /my-bug-reports?report=<uuid> and should
  // auto-expand that report once the owner's list loads. The id may reference
  // a report that is no longer in the owner's list — that simply matches no
  // row, so nothing auto-expands.
  const requestedReportId = searchParams.get("report");
  const [expandedId, setExpandedId] = useState<string | null>(requestedReportId);

  // Re-sync whenever the search param changes so navigating here again from a
  // second notification (without a remount, since we're already on this route)
  // still expands the newly-referenced report.
  useEffect(() => {
    if (requestedReportId) setExpandedId(requestedReportId);
  }, [requestedReportId]);

  const query = useQuery({ queryKey: queryKeys.myBugReports(), queryFn: getMyBugReports });
  const reports = query.data?.items ?? [];

  const bugReportSeverityLabel = (severity: BugReportSeverity) => t(`bug_reports.severity_${severity}`);
  const bugReportStatusLabel = (status: BugReportStatus) => t(`bug_reports.status_${status}`);

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-3">
        <h2 className="text-xl font-semibold">{t("my_bug_reports.title")}</h2>

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
                    onClick={() => setExpandedId(isExpanded ? null : report.id)}
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
                    <span className="flex-1 truncate">{report.description}</span>
                    <span className="text-xs text-gray-500 dark:text-gray-400 shrink-0">
                      {report.comment_count} {t("bug_reports.comment_count")}
                    </span>
                    <span className="text-gray-400 shrink-0">{isExpanded ? "▲" : "▼"}</span>
                  </button>
                  {isExpanded && (
                    <div className="border-t dark:border-gray-600">
                      <BugReportCommentsPanel reportId={report.id} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </Layout>
  );
}
