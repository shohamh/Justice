import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  listBugReports,
  updateBugReportStatus,
  getBugReportJson,
  fetchBugReportScreenshot,
  importBugReports,
  BugReportSummary,
  BugReportSeverity,
  BugReportStatus,
  BugReportImportSummary,
} from "../../api/bugReports";
import { translateApiError } from "../../utils/translateApiError";
import BugReportDetailModal from "../../components/BugReportDetailModal";
import { usePagePagination } from "../../hooks/usePagePagination";
import { DataTable, ColDef } from "../../components/DataTable";

const SEVERITY_COLORS: Record<BugReportSeverity, string> = {
  low: "bg-gray-100 text-gray-700",
  medium: "bg-yellow-100 text-yellow-800",
  high: "bg-red-100 text-red-800",
};

const STATUS_ICONS: Record<BugReportStatus, string> = {
  open: "🔴",
  in_progress: "🟡",
  resolved: "🟢",
  wont_fix: "⚪",
};

const STATUS_ROW_BG: Record<BugReportStatus, string> = {
  open: "bg-red-50 dark:bg-red-950/30",
  in_progress: "bg-yellow-50 dark:bg-yellow-950/30",
  resolved: "bg-green-50 dark:bg-green-950/30",
  wont_fix: "bg-gray-50 dark:bg-gray-800/50",
};

const STATUS_ORDER: BugReportStatus[] = ["open", "in_progress", "resolved", "wont_fix"];

export function BugReportsContent() {
  const { t } = useTranslation();
  const bugReportSeverityLabel = (severity: BugReportSeverity) => t(`bug_reports.severity_${severity}`);
  const bugReportStatusLabel = (status: BugReportStatus) => t(`bug_reports.status_${status}`);
  const [severityFilter, setSeverityFilter] = useState<BugReportSeverity | "">("");
  const [statusFilter, setStatusFilter] = useState<BugReportStatus | "">("");
  const { page, setPage, offset, limit } = usePagePagination({ limit: 20 });
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [openCommentsFor, setOpenCommentsFor] = useState<string | null>(null);
  const [jsonById, setJsonById] = useState<Record<string, string>>({});
  const [screenshotUrlById, setScreenshotUrlById] = useState<Record<string, string>>({});
  const [statusErrorById, setStatusErrorById] = useState<Record<string, string>>({});
  const [jsonErrorById, setJsonErrorById] = useState<Record<string, string>>({});
  const [screenshotErrorById, setScreenshotErrorById] = useState<Record<string, string>>({});
  const [importing, setImporting] = useState(false);
  const [importSummary, setImportSummary] = useState<BugReportImportSummary | null>(null);
  const [importError, setImportError] = useState("");
  const importInputRef = useRef<HTMLInputElement>(null);

  // Keep a ref in sync so the unmount cleanup can revoke whatever URLs were
  // accumulated without re-registering the effect on every fetch.
  const screenshotUrlByIdRef = useRef(screenshotUrlById);
  screenshotUrlByIdRef.current = screenshotUrlById;

  useEffect(() => {
    return () => {
      Object.values(screenshotUrlByIdRef.current).forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

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

  useEffect(() => {
    if (pages > 0 && page > pages) setPage(pages);
  }, [page, pages, setPage]);

  async function handleStatusChange(id: string, status: BugReportStatus) {
    setStatusErrorById((prev) => ({ ...prev, [id]: "" }));
    try {
      await updateBugReportStatus(id, status);
      await query.refetch();
    } catch (err: unknown) {
      setStatusErrorById((prev) => ({
        ...prev,
        [id]: translateApiError(err, t, "שגיאה בעדכון הסטטוס"),
      }));
    }
  }

  async function loadScreenshot(id: string) {
    if (screenshotUrlById[id]) return;
    setScreenshotErrorById((prev) => ({ ...prev, [id]: "" }));
    try {
      const blob = await fetchBugReportScreenshot(id);
      setScreenshotUrlById((prev) => ({ ...prev, [id]: URL.createObjectURL(blob) }));
    } catch (err: unknown) {
      setScreenshotErrorById((prev) => ({
        ...prev,
        [id]: translateApiError(err, t, "שגיאה בטעינת צילום המסך"),
      }));
    }
  }

  function toggleExpand(report: BugReportSummary) {
    if (expandedId === report.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(report.id);
    if (report.has_screenshot) void loadScreenshot(report.id);
  }

  async function handleImportFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    setImporting(true);
    setImportError("");
    setImportSummary(null);
    try {
      const summary = await importBugReports(Array.from(fileList));
      setImportSummary(summary);
      await query.refetch();
    } catch (err: unknown) {
      setImportError(translateApiError(err, t, "שגיאה בייבוא הקבצים"));
    } finally {
      setImporting(false);
      if (importInputRef.current) importInputRef.current.value = "";
    }
  }

  async function loadJson(id: string) {
    if (jsonById[id]) return;
    setJsonErrorById((prev) => ({ ...prev, [id]: "" }));
    try {
      const data = await getBugReportJson(id);
      setJsonById((prev) => ({ ...prev, [id]: JSON.stringify(data, null, 2) }));
    } catch (err: unknown) {
      setJsonErrorById((prev) => ({
        ...prev,
        [id]: translateApiError(err, t, "שגיאה בטעינת ה-JSON"),
      }));
    }
  }

  const bugReportColumns: ColDef<BugReportSummary>[] = [
    {
      id: "created_at",
      header: "תאריך",
      cell: (report) => new Date(report.created_at).toLocaleString("he-IL"),
      sortValue: (report) => report.created_at,
    },
    {
      id: "reporter",
      header: "מדווח",
      cell: (report) => (report.user_snapshot?.full_name as string) ?? "—",
      sortValue: (report) => (report.user_snapshot?.full_name as string) ?? "",
      filterValue: (report) => (report.user_snapshot?.full_name as string) ?? "",
    },
    {
      id: "severity",
      header: "חומרה",
      cell: (report) => (
        <span className={`px-2 py-0.5 rounded text-xs ${SEVERITY_COLORS[report.severity]}`}>
          {bugReportSeverityLabel(report.severity)}
        </span>
      ),
      sortValue: (report) => report.severity,
    },
    {
      id: "status",
      header: "סטטוס",
      cell: (report) => (
        <>
          <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
            {STATUS_ORDER.map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={report.status === s}
                title={bugReportStatusLabel(s)}
                onClick={() => handleStatusChange(report.id, s)}
                className={`w-7 h-7 flex items-center justify-center rounded text-sm ${
                  report.status === s ? "ring-2 ring-indigo-500" : "opacity-40 hover:opacity-70"
                }`}
                data-testid={`bug-report-status-${s}-${report.id}`}
              >
                {STATUS_ICONS[s]}
              </button>
            ))}
          </div>
          {statusErrorById[report.id] && (
            <p className="text-xs text-red-500 mt-1" data-testid={`bug-report-status-error-${report.id}`}>
              {statusErrorById[report.id]}
            </p>
          )}
        </>
      ),
      sortValue: (report) => report.status,
    },
    {
      id: "description",
      header: "תיאור",
      cell: (report) => <span className="truncate max-w-xs block">{report.description}</span>,
      filterValue: (report) => report.description,
    },
  ];

  return (
    <div dir="rtl">
      <div className="flex items-center gap-2 mb-4">
        <label
          className={`text-sm px-3 py-1.5 rounded border cursor-pointer dark:border-gray-600 ${importing ? "opacity-60 cursor-not-allowed" : "hover:bg-gray-50 dark:hover:bg-gray-700"}`}
        >
          {importing ? "מייבא..." : "ייבוא קבצי JSON"}
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            multiple
            disabled={importing}
            onChange={(e) => { void handleImportFiles(e.target.files); }}
            className="hidden"
            data-testid="bug-report-import-input"
          />
        </label>
        {importError && (
          <span className="text-xs text-red-500" data-testid="bug-report-import-error">{importError}</span>
        )}
        {importSummary && (
          <span className="text-xs text-gray-600 dark:text-gray-300" data-testid="bug-report-import-summary">
            יובאו {importSummary.results.filter((r) => r.status === "imported").length} מתוך {importSummary.results.length}
            {importSummary.results.some((r) => r.status !== "imported") && (
              <>
                {" "}
                (
                {importSummary.results
                  .filter((r) => r.status !== "imported")
                  .map((r) => `${r.filename}: ${r.status === "already_exists" ? "כבר קיים" : r.detail ?? "שגיאה"}`)
                  .join(", ")}
                )
              </>
            )}
          </span>
        )}
      </div>
      <div className="flex gap-2 mb-4">
        <select
          value={severityFilter}
          onChange={(e) => { setSeverityFilter(e.target.value as BugReportSeverity | ""); setPage(1); }}
          className="border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600"
          data-testid="bug-report-filter-severity"
        >
          <option value="">כל החומרות</option>
          <option value="low">{bugReportSeverityLabel("low")}</option>
          <option value="medium">{bugReportSeverityLabel("medium")}</option>
          <option value="high">{bugReportSeverityLabel("high")}</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value as BugReportStatus | ""); setPage(1); }}
          className="border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600"
          data-testid="bug-report-filter-status"
        >
          <option value="">כל הסטטוסים</option>
          <option value="open">{bugReportStatusLabel("open")}</option>
          <option value="in_progress">{bugReportStatusLabel("in_progress")}</option>
          <option value="resolved">{bugReportStatusLabel("resolved")}</option>
          <option value="wont_fix">{bugReportStatusLabel("wont_fix")}</option>
        </select>
      </div>

      {query.isLoading && (
        <p className="text-sm text-gray-500 p-4" data-testid="bug-reports-loading">טוען...</p>
      )}
      {query.isError && (
        <p className="text-sm text-red-500 p-4" data-testid="bug-reports-error">שגיאה בטעינת הדיווחים</p>
      )}
      {!query.isLoading && !query.isError && (
        <DataTable<BugReportSummary>
          columns={bugReportColumns}
          data={items}
          rowTestId={(report) => `bug-report-row-${report.id}`}
          rowClassName={(report) => `border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 ${STATUS_ROW_BG[report.status]}`}
          expandable={{
            isExpanded: (report) => expandedId === report.id,
            onToggle: (report) => toggleExpand(report),
            content: (report) => (
              <div className="p-4">
                <p className="mb-2"><strong>תיאור מלא:</strong> {report.description}</p>
                <p className="mb-2"><strong>מסלול:</strong> {report.route}</p>
                {report.has_screenshot && screenshotUrlById[report.id] && (
                  <img
                    src={screenshotUrlById[report.id]}
                    alt=""
                    className="max-w-md rounded border dark:border-gray-600 mb-2"
                  />
                )}
                {screenshotErrorById[report.id] && (
                  <p className="text-xs text-red-500 mb-2" data-testid={`bug-report-screenshot-error-${report.id}`}>
                    {screenshotErrorById[report.id]}
                  </p>
                )}
                <p className="mb-1"><strong>תמונת מצב משתמש:</strong></p>
                <ul className="list-disc pr-5 mb-2 text-xs">
                  <li>דרגה: {(report.user_snapshot?.rank as string) ?? "—"}</li>
                  <li>תפקיד: {(report.user_snapshot?.role as string) ?? "—"}</li>
                  <li>מספר אישי: {(report.user_snapshot?.personal_number as string) ?? "—"}</li>
                </ul>
                <p className="mb-1"><strong>מסלול ניווט:</strong></p>
                <ul className="list-disc pr-5 mb-2 text-xs">
                  {(report.nav_history ?? []).map((h, i) => (
                    <li key={i}>
                      <Link to={h.path} className="text-indigo-600 hover:text-indigo-800 hover:underline" target="_blank" rel="noopener noreferrer">
                        {h.path}
                      </Link>
                      {" — "}{new Date(h.timestamp).toLocaleString("he-IL")}
                    </li>
                  ))}
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
                <button
                  onClick={(e) => { e.stopPropagation(); setOpenCommentsFor(report.id); }}
                  className="text-xs text-indigo-600 hover:text-indigo-800 mr-3"
                  data-testid={`bug-report-comments-${report.id}`}
                >
                  {t("bug_reports.comment_button")}
                </button>
                {jsonErrorById[report.id] && (
                  <p className="text-xs text-red-500 mt-1" data-testid={`bug-report-json-error-${report.id}`}>
                    {jsonErrorById[report.id]}
                  </p>
                )}
                {jsonById[report.id] && (
                  <pre className="text-xs bg-gray-100 dark:bg-gray-800 p-2 rounded mt-2 overflow-x-auto">
                    {jsonById[report.id]}
                  </pre>
                )}
              </div>
            ),
          }}
        />
      )}

      {pages > 1 && (
        <div className="flex justify-center gap-2 mt-4">
          {Array.from({ length: pages }, (_, i) => (
            <button
              key={i}
              onClick={() => setPage(i + 1)}
              className={`px-3 py-1 rounded text-sm ${page === i + 1 ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-700 dark:text-gray-300"}`}
            >
              {i + 1}
            </button>
          ))}
        </div>
      )}

      {openCommentsFor && (
        <BugReportDetailModal reportId={openCommentsFor} onClose={() => setOpenCommentsFor(null)} />
      )}
    </div>
  );
}
