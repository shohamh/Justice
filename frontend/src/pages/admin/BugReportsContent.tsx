import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  listBugReports,
  updateBugReportStatus,
  getBugReportJson,
  fetchBugReportScreenshot,
  BugReportSummary,
  BugReportSeverity,
  BugReportStatus,
} from "../../api/bugReports";

const SEVERITY_LABELS: Record<BugReportSeverity, string> = { low: "נמוכה", medium: "בינונית", high: "גבוהה" };
const SEVERITY_COLORS: Record<BugReportSeverity, string> = {
  low: "bg-gray-100 text-gray-700",
  medium: "bg-yellow-100 text-yellow-800",
  high: "bg-red-100 text-red-800",
};
const STATUS_LABELS: Record<BugReportStatus, string> = { open: "פתוח", in_progress: "בטיפול", resolved: "טופל" };

export function BugReportsContent() {
  const [severityFilter, setSeverityFilter] = useState<BugReportSeverity | "">("");
  const [statusFilter, setStatusFilter] = useState<BugReportStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [jsonById, setJsonById] = useState<Record<string, string>>({});
  const [screenshotUrlById, setScreenshotUrlById] = useState<Record<string, string>>({});
  const limit = 20;

  const query = useQuery({
    queryKey: ["bug-reports", severityFilter, statusFilter, offset],
    queryFn: () =>
      listBugReports({
        severity: severityFilter || undefined,
        status: statusFilter || undefined,
        offset,
        limit,
      }),
  });

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const pages = Math.ceil(total / limit);

  async function handleStatusChange(id: string, status: BugReportStatus) {
    await updateBugReportStatus(id, status);
    await query.refetch();
  }

  async function loadScreenshot(id: string) {
    if (screenshotUrlById[id]) return;
    const blob = await fetchBugReportScreenshot(id);
    setScreenshotUrlById((prev) => ({ ...prev, [id]: URL.createObjectURL(blob) }));
  }

  function toggleExpand(report: BugReportSummary) {
    if (expandedId === report.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(report.id);
    if (report.has_screenshot) void loadScreenshot(report.id);
  }

  async function loadJson(id: string) {
    if (jsonById[id]) return;
    const data = await getBugReportJson(id);
    setJsonById((prev) => ({ ...prev, [id]: JSON.stringify(data, null, 2) }));
  }

  return (
    <div dir="rtl">
      <div className="flex gap-2 mb-4">
        <select
          value={severityFilter}
          onChange={(e) => { setSeverityFilter(e.target.value as BugReportSeverity | ""); setOffset(0); }}
          className="border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600"
          data-testid="bug-report-filter-severity"
        >
          <option value="">כל החומרות</option>
          <option value="low">נמוכה</option>
          <option value="medium">בינונית</option>
          <option value="high">גבוהה</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value as BugReportStatus | ""); setOffset(0); }}
          className="border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600"
          data-testid="bug-report-filter-status"
        >
          <option value="">כל הסטטוסים</option>
          <option value="open">פתוח</option>
          <option value="in_progress">בטיפול</option>
          <option value="resolved">טופל</option>
        </select>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-right border-b dark:border-gray-700">
            <th className="p-2">תאריך</th>
            <th className="p-2">מדווח</th>
            <th className="p-2">חומרה</th>
            <th className="p-2">סטטוס</th>
            <th className="p-2">תיאור</th>
          </tr>
        </thead>
        <tbody>
          {items.map((report) => (
            <Fragment key={report.id}>
              <tr
                className="border-b dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700"
                onClick={() => toggleExpand(report)}
                data-testid={`bug-report-row-${report.id}`}
              >
                <td className="p-2">{new Date(report.created_at).toLocaleString("he-IL")}</td>
                <td className="p-2">{(report.user_snapshot?.full_name as string) ?? "—"}</td>
                <td className="p-2">
                  <span className={`px-2 py-0.5 rounded text-xs ${SEVERITY_COLORS[report.severity]}`}>
                    {SEVERITY_LABELS[report.severity]}
                  </span>
                </td>
                <td className="p-2" onClick={(e) => e.stopPropagation()}>
                  <select
                    value={report.status}
                    onChange={(e) => handleStatusChange(report.id, e.target.value as BugReportStatus)}
                    className="border rounded px-1 py-0.5 text-xs dark:bg-gray-700 dark:border-gray-600"
                    data-testid={`bug-report-status-${report.id}`}
                  >
                    <option value="open">{STATUS_LABELS.open}</option>
                    <option value="in_progress">{STATUS_LABELS.in_progress}</option>
                    <option value="resolved">{STATUS_LABELS.resolved}</option>
                  </select>
                </td>
                <td className="p-2 truncate max-w-xs">{report.description}</td>
              </tr>
              {expandedId === report.id && (
                <tr className="border-b dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
                  <td colSpan={5} className="p-4">
                    <p className="mb-2"><strong>תיאור מלא:</strong> {report.description}</p>
                    {report.has_screenshot && screenshotUrlById[report.id] && (
                      <img
                        src={screenshotUrlById[report.id]}
                        alt=""
                        className="max-w-md rounded border dark:border-gray-600 mb-2"
                      />
                    )}
                    <p className="mb-1"><strong>מסלול ניווט:</strong></p>
                    <ul className="list-disc pr-5 mb-2 text-xs">
                      {(report.nav_history ?? []).map((h, i) => <li key={i}>{h.path} — {h.timestamp}</li>)}
                    </ul>
                    <p className="mb-1"><strong>פעולות אחרונות ביומן:</strong></p>
                    <ul className="list-disc pr-5 mb-2 text-xs">
                      {(report.audit_snapshot ?? []).map((a, i) => (
                        <li key={i}>{String(a.action)} — {String(a.entity_type)}</li>
                      ))}
                    </ul>
                    <button
                      onClick={() => loadJson(report.id)}
                      className="text-xs text-indigo-600 hover:text-indigo-800"
                      data-testid={`bug-report-view-json-${report.id}`}
                    >
                      הצג JSON
                    </button>
                    {jsonById[report.id] && (
                      <pre className="text-xs bg-gray-100 dark:bg-gray-800 p-2 rounded mt-2 overflow-x-auto">
                        {jsonById[report.id]}
                      </pre>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>

      {pages > 1 && (
        <div className="flex justify-center gap-2 mt-4">
          {Array.from({ length: pages }, (_, i) => (
            <button
              key={i}
              onClick={() => setOffset(i * limit)}
              className={`px-3 py-1 rounded text-sm ${offset === i * limit ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-700 dark:text-gray-300"}`}
            >
              {i + 1}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
