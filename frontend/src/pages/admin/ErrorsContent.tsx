import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Check, Copy, ClipboardCopy } from "lucide-react";
import { clearAdminErrors, listAdminErrors, markAdminErrorsRead, markAllAdminErrorsRead, type ErrorLogEntry, type PaginatedErrorLogs } from "../../api/bugReports";
import ConfirmDialog from "../../components/ConfirmDialog";
import SoldierLink from "../../components/SoldierLink";

function buildErrorReport(entry: ErrorLogEntry): string {
  const prompt = `This is a ${entry.source} error in my app, here are its details. Investigate it and fix it.`;
  const lines = [
    prompt,
    "",
    `Source: ${entry.source}`,
    `Timestamp: ${entry.timestamp ?? "unknown"}`,
    `Message: ${entry.message}`,
  ];
  if (entry.request_id) lines.push(`Request ID: ${entry.request_id}`);
  lines.push("", "Details:", JSON.stringify(entry.details, null, 2));
  return lines.join("\n");
}

const PAGE_SIZE = 50;

export function ErrorsContent() {
  const { t } = useTranslation();
  const [source, setSource] = useState<"" | "backend" | "frontend">("");
  const [page, setPage] = useState(1);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [clearThrough, setClearThrough] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const queryClient = useQueryClient();
  const queryKey = ["admin-errors", source, page, from, to];
  const query = useQuery({
    queryKey,
    queryFn: () => listAdminErrors({ source: source || undefined, offset: (page - 1) * PAGE_SIZE, limit: PAGE_SIZE, from: from ? new Date(from).toISOString() : undefined, to: to ? new Date(to).toISOString() : undefined }),
  });
  const items = useMemo(() => query.data?.items ?? [], [query.data?.items]);
  const pages = Math.ceil((query.data?.total ?? 0) / PAGE_SIZE);
  const label = (key: string, fallback: string) => t(key, { defaultValue: fallback });

  async function markErrorRead(entry: ErrorLogEntry) {
    if (!entry.unread) return;
    queryClient.setQueryData<PaginatedErrorLogs>(queryKey, (data) => data ? { ...data, items: data.items.map((item) => item.record_key === entry.record_key ? { ...item, unread: false } : item) } : data);
    await markAdminErrorsRead([{ record_key: entry.record_key, source: entry.source }]);
    void queryClient.invalidateQueries({ queryKey: ["admin-errors-unread"] });
  }

  async function handleMarkAllRead() {
    await markAllAdminErrorsRead({ source: source || undefined, from: from ? new Date(from).toISOString() : undefined, to: to ? new Date(to).toISOString() : undefined });
    queryClient.setQueryData<PaginatedErrorLogs>(queryKey, (data) => data ? { ...data, items: data.items.map((item) => ({ ...item, unread: false })) } : data);
    void queryClient.invalidateQueries({ queryKey: ["admin-errors-unread"] });
  }

  async function handleClear() {
    if (!clearThrough) return;
    setConfirmClear(true);
  }

  async function confirmClearErrors() {
    setConfirmClear(false);
    await clearAdminErrors(new Date(clearThrough).toISOString());
    setClearThrough("");
    await query.refetch();
    void queryClient.invalidateQueries({ queryKey: ["admin-errors-unread"] });
  }

  return (
    <div dir="rtl" data-testid="admin-errors-content">
      <div className="flex items-center gap-2 mb-4">
        <label htmlFor="admin-error-source" className="text-sm">{label("admin_errors.source", "\u05de\u05e7\u05d5\u05e8")}</label>
        <select id="admin-error-source" value={source} onChange={(event) => { setSource(event.target.value as typeof source); setPage(1); }} className="border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600" data-testid="admin-errors-source-filter">
          <option value="">{label("admin_errors.all_sources", "\u05db\u05dc \u05d4\u05de\u05e7\u05d5\u05e8\u05d5\u05ea")}</option>
          <option value="backend">{label("admin_errors.backend", "\u05e6\u05d3 \u05e9\u05e8\u05ea")}</option>
          <option value="frontend">{label("admin_errors.frontend", "\u05e6\u05d3 \u05dc\u05e7\u05d5\u05d7")}</option>
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-2 mb-4 text-sm">
        <label htmlFor="admin-errors-from">{label("admin_errors.from", "\u05de\u05ea\u05d0\u05e8\u05d9\u05da")}</label>
        <div className="relative inline-flex items-center">
          <input id="admin-errors-from" data-testid="admin-errors-from" type="datetime-local" value={from} onChange={(event) => { setFrom(event.target.value); setPage(1); }} className="border rounded px-2 py-1 dark:bg-gray-700 dark:border-gray-600" />
          {from && <button type="button" aria-label="נקה תאריך התחלה" onClick={() => { setFrom(""); setPage(1); }} className="absolute left-1 text-gray-500 hover:text-red-600">×</button>}
        </div>
        <label htmlFor="admin-errors-to">{label("admin_errors.to", "\u05e2\u05d3")}</label>
        <div className="relative inline-flex items-center">
          <input id="admin-errors-to" type="datetime-local" value={to} onChange={(event) => { setTo(event.target.value); setPage(1); }} className="border rounded px-2 py-1 dark:bg-gray-700 dark:border-gray-600" />
          {to && <button type="button" aria-label="נקה תאריך הסיום" onClick={() => { setTo(""); setPage(1); }} className="absolute left-1 text-gray-500 hover:text-red-600">×</button>}
        </div>
        <label htmlFor="admin-errors-clear-through">{label("admin_errors.clear_through", "\u05e0\u05e7\u05d4 \u05e2\u05d3")}</label>
        <div className="relative inline-flex items-center">
          <input id="admin-errors-clear-through" type="datetime-local" value={clearThrough} onChange={(event) => setClearThrough(event.target.value)} className="border rounded px-2 py-1 dark:bg-gray-700 dark:border-gray-600" />
          {clearThrough && <button type="button" aria-label="נקה תאריך ניקוי" onClick={() => setClearThrough("")} className="absolute left-1 text-gray-500 hover:text-red-600">×</button>}
        </div>
        <button type="button" onClick={() => void handleClear()} disabled={!clearThrough} className="rounded bg-red-600 text-white px-3 py-1 disabled:opacity-50">{label("admin_errors.clear", "\u05e0\u05e7\u05d4")}</button>
        <button type="button" data-testid="admin-errors-mark-all-read" onClick={() => void handleMarkAllRead()} className="rounded bg-gray-600 text-white px-3 py-1">סמן הכל כנקרא</button>
      </div>
      {query.isLoading && <p className="text-sm text-gray-500 p-4">{label("admin_errors.loading", "\u05d8\u05d5\u05e2\u05df \u05e9\u05d2\u05d9\u05d0\u05d5\u05ea...")}</p>}
      {query.isError && <p className="text-sm text-red-500 p-4">{label("admin_errors.load_error", "\u05e9\u05d2\u05d9\u05d0\u05d4 \u05d1\u05d8\u05e2\u05d9\u05e0\u05ea \u05d4\u05e9\u05d2\u05d9\u05d0\u05d5\u05ea")}</p>}
      {!query.isLoading && !query.isError && items.length === 0 && <p className="text-sm text-gray-500 p-4">{label("admin_errors.empty", "\u05dc\u05d0 \u05e0\u05e8\u05e9\u05de\u05d5 \u05e9\u05d2\u05d9\u05d0\u05d5\u05ea")}</p>}
      {!query.isLoading && !query.isError && items.length > 0 && <div className="space-y-2">{items.map((entry, index) => <ErrorRow key={`${entry.timestamp}-${entry.request_id}-${index}`} entry={entry} onOpen={() => void markErrorRead(entry)} />)}</div>}
      {pages > 1 && <div className="flex justify-center gap-2 mt-4">{Array.from({ length: pages }, (_, index) => <button key={index} type="button" onClick={() => setPage(index + 1)} className={`px-3 py-1 rounded text-sm ${page === index + 1 ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-700 dark:text-gray-300"}`}>{index + 1}</button>)}</div>}
      <ConfirmDialog
        open={confirmClear}
        title={label("admin_errors.clear", "נקה")}
        message={label("admin_errors.confirm_clear", "לנקות כל השגיאות עד תאריך זה?")}
        danger
        onConfirm={() => void confirmClearErrors()}
        onClose={() => setConfirmClear(false)}
      />
    </div>
  );
}

function ErrorRow({ entry, onOpen }: { entry: ErrorLogEntry; onOpen: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const frontendDetails = entry.details.frontend;
  const isFrontendDetails = entry.source === "frontend" && frontendDetails && typeof frontendDetails === "object";
  const detailMessage = isFrontendDetails && "message" in frontendDetails ? frontendDetails.message : undefined;
  const frontendMethod = isFrontendDetails && "method" in frontendDetails && typeof frontendDetails.method === "string" ? frontendDetails.method.toUpperCase() : undefined;
  const frontendUrl = isFrontendDetails && "url" in frontendDetails && typeof frontendDetails.url === "string" ? frontendDetails.url : undefined;
  const frontendRequest = [frontendMethod, frontendUrl].filter(Boolean).join(" ");
  const stack = entry.source === "frontend" && frontendDetails && typeof frontendDetails === "object" && "stack" in frontendDetails ? frontendDetails.stack : entry.details.traceback;
  const request = entry.details.request;
  const path = entry.source === "backend" && request && typeof request === "object" && "path" in request ? request.path : entry.details.path;
  const user = entry.details.user;
  const userId = user && typeof user === "object" && "id" in user && typeof user.id === "string" ? user.id : undefined;
  const userName = user && typeof user === "object" && "name" in user && typeof user.name === "string" ? user.name : undefined;
  const ip = typeof entry.details.ip === "string" ? entry.details.ip : undefined;
  const toggle = () => { onOpen(); setExpanded((value) => !value); };
  return (
    <article className="border rounded dark:border-gray-600 p-3 cursor-pointer" data-testid={`admin-error-${entry.request_id ?? "unknown"}`} onClick={toggle}>
      <div className="flex items-center justify-between gap-2">
        <button type="button" onClick={(event) => { event.stopPropagation(); toggle(); }} className="flex-1 text-right">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            {entry.unread && <span className="inline-block h-2 w-2 rounded-full bg-red-500 shrink-0" data-testid={`admin-error-unread-${entry.record_key}`} aria-label="לא נקרא" />}
            <span className={`font-semibold ${entry.source === "backend" ? "text-red-600" : "text-blue-600 dark:text-blue-400"}`}>{entry.source}</span>
            <span>{entry.timestamp ? new Date(entry.timestamp).toLocaleString("he-IL") : "—"}</span>
          </div>
        </button>
        <CopyReportButton entry={entry} />
      </div>
      {(userId && userName || ip) && <div className="mt-1 text-xs text-gray-600 dark:text-gray-300 flex items-center gap-2">
        {userId && userName && <><span>משתמש:</span><SoldierLink id={userId} name={userName} /></>}
        {ip && <span dir="ltr">IP: {ip}</span>}
      </div>}
      {entry.source === "backend" && <p dir="ltr" className="mt-2 text-sm whitespace-pre-wrap text-left" data-testid={`admin-error-message-${entry.request_id ?? "unknown"}`}>{entry.message}</p>}
      {entry.source === "frontend" && typeof detailMessage === "string" && <p dir="ltr" className="mt-2 text-sm whitespace-pre-wrap text-left" data-testid={`admin-error-message-${entry.request_id ?? "unknown"}`}>{detailMessage}</p>}
      {entry.source === "frontend" && frontendRequest && <p dir="ltr" className="mt-1 text-xs text-gray-600 dark:text-gray-300 text-left" data-testid={`admin-error-request-${entry.request_id ?? "unknown"}`}>{frontendRequest}</p>}
      {entry.source === "backend" && typeof path === "string" && <p dir="ltr" className="mt-1 text-xs text-gray-600 dark:text-gray-300 text-left" data-testid={`admin-error-path-${entry.request_id ?? "unknown"}`}>{path}</p>}
      {expanded && <>
        {typeof stack === "string" && <><h3 className="mt-3 text-sm font-semibold">Traceback</h3><CopyBlock value={stack} testId={`admin-error-stack-${entry.request_id ?? "unknown"}`} copyTestId={`admin-error-copy-stack-${entry.request_id ?? "unknown"}`} /></>}
        <h3 className="mt-3 text-sm font-semibold">Full details (JSON)</h3>
        <CopyBlock value={JSON.stringify(entry.details, null, 2)} testId={`admin-error-json-${entry.request_id ?? "unknown"}`} copyTestId={`admin-error-copy-json-${entry.request_id ?? "unknown"}`} />
      </>}
    </article>
  );
}

function CopyReportButton({ entry }: { entry: ErrorLogEntry }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (!navigator.clipboard?.writeText) return;
    try {
      await navigator.clipboard.writeText(buildErrorReport(entry));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button
      type="button"
      title={copied ? "הועתק" : "העתק דוח שגיאה מלא לתיקון"}
      aria-label={copied ? "הועתק" : "העתק דוח שגיאה מלא לתיקון"}
      className="shrink-0 p-1.5 rounded text-gray-500 hover:text-gray-900 hover:bg-gray-100 dark:hover:text-gray-100 dark:hover:bg-gray-700"
      data-testid={`admin-error-copy-report-${entry.request_id ?? "unknown"}`}
      onClick={(event) => { event.stopPropagation(); void handleCopy(); }}
    >
      {copied ? <Check className="h-4 w-4 text-green-600" aria-hidden="true" /> : <ClipboardCopy className="h-4 w-4" aria-hidden="true" />}
    </button>
  );
}

function CopyBlock({ value, testId, copyTestId }: { value: string; testId: string; copyTestId: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (!navigator.clipboard?.writeText) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="relative mt-3" dir="ltr">
      <button type="button" aria-label={copied ? "הועתק" : "העתק"} className="absolute top-1 right-1 p-1 text-gray-500 hover:text-gray-900 dark:hover:text-gray-100" data-testid={copyTestId} onClick={(event) => { event.stopPropagation(); void handleCopy(); }}>
        {copied ? <Check className="h-3.5 w-3.5 text-green-600" aria-hidden="true" data-testid={`admin-error-copy-success-${testId.replace("admin-error-stack-", "stack-").replace("admin-error-json-", "json-")}`} /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
      </button>
      <pre className="p-2 pr-8 rounded bg-gray-100 dark:bg-gray-800 text-xs overflow-auto max-h-96 text-left whitespace-pre-wrap" data-testid={testId}>{value}</pre>
    </div>
  );
}
