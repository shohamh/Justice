import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DataTable, type ColDef } from "../../components/DataTable";
import {
  getExchangeSyncSummary, listExchangeSyncEvents, retryExchangeSyncEvent,
  type ExchangeSyncEvent, type ExchangeSourceType,
} from "../../api/exchangeCalendarSync";

const statusLabels: Record<string, string> = {
  queued: "בתור", in_progress: "בעבודה", synced: "סונכרן", partial: "חלקי",
  retry_wait: "ממתין לניסיון חוזר", failed: "נכשל", cancelled: "בוטל",
};
const sourceLabels: Record<ExchangeSourceType, string> = {
  duty_shift: "משמרת", duty_assignment: "שיבוץ", range_event: "מטווח",
};
const attendeeRoleLabels: Record<string, string> = {
  assigned_soldier: "חייל משובץ",
  reserve: "חייל מילואים",
  called_up_reserve: "חייל מילואים שהוקפץ",
  direct_commander: "מפקד ישיר",
  responsible_duty_manager: "אחראי תורנות",
  contact: "איש קשר",
};
const countLabels = [
  ["eligible", "אירועים זכאים"], ["synced", "סונכרנו"], ["queued", "בתור"],
  ["in_progress", "בעבודה"], ["partial", "חלקי"], ["retry_wait", "ממתינים לניסיון חוזר"],
  ["failed", "נכשלו"],
] as const;
const recentLabels = [
  ["created", "נוצרו"], ["updated", "עודכנו"], ["cancelled", "בוטלו"],
  ["partial", "חלקיים"], ["failed", "נכשלו"],
] as const;

function formatTime(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : new Intl.DateTimeFormat("he-IL", {
    dateStyle: "short", timeStyle: "short", timeZone: "Asia/Jerusalem",
  }).format(parsed);
}

export default function ExchangeCalendarSyncContent() {
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [history, setHistory] = useState<ExchangeSyncEvent | null>(null);
  const [retryResult, setRetryResult] = useState<string | null>(null);
  const summary = useQuery({ queryKey: ["exchange-sync-summary"], queryFn: getExchangeSyncSummary });
  const events = useQuery({
    queryKey: ["exchange-sync-events", offset],
    queryFn: () => listExchangeSyncEvents(25, offset),
  });
  const retry = useMutation({
    mutationFn: ({ sourceType, sourceId }: { sourceType: ExchangeSourceType; sourceId: string }) =>
      retryExchangeSyncEvent(sourceType, sourceId),
    onSuccess: () => {
      setRetryResult("הבקשה נוספה לתור (queued). הסנכרון יתבצע ברקע.");
      void queryClient.invalidateQueries({ queryKey: ["exchange-sync-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["exchange-sync-events"] });
    },
  });

  const columns: ColDef<ExchangeSyncEvent>[] = [
    { id: "source", header: "מקור", cell: (row) => <div data-testid={`exchange-sync-event-${row.source_id}`}>{sourceLabels[row.source_type]} · {row.source_date ?? "—"}</div> },
    { id: "status", header: "מצב", cell: (row) => <span>{statusLabels[row.status] ?? row.status} <span className="text-xs text-gray-500">({row.status})</span></span> },
    { id: "last_attempt", header: "ניסיון אחרון", cell: (row) => formatTime(row.last_attempt_at) },
    { id: "last_success", header: "הצלחה אחרונה", cell: (row) => formatTime(row.last_success_at) },
    { id: "problem", header: "שגיאות וכתובות חסרות", cell: (row) => (
      <div className="space-y-1">
        {row.error && <div>{row.error}</div>}
        {row.current_projection_problems.length > 0 && (
          <div>
            <span className="font-medium">בעיות נוכחיות בנתוני המשתתפים:</span>{" "}
            {row.current_projection_problems.map((problem, index) => <span key={`${problem.code}-${problem.attendee_name ?? "unknown"}-${index}`}>
              {index > 0 && "; "}
              {problem.attendee_name && <span className="font-medium">{problem.attendee_name} ({attendeeRoleLabels[problem.attendee_role ?? ""] ?? "משתתף"}): </span>}
              {problem.message}
            </span>)}
          </div>
        )}
        {!row.error && row.current_projection_problems.length === 0 && "—"}
      </div>
    ) },
    { id: "actions", header: "", cell: (row) => <div className="flex flex-wrap gap-2">
      <button type="button" data-testid={`exchange-sync-history-${row.source_id}`} className="text-indigo-600 dark:text-indigo-300 underline" onClick={() => setHistory(row)}>היסטוריה</button>
      {(["failed", "partial", "retry_wait"] as string[]).includes(row.status) && (
        <button type="button" data-testid={`exchange-sync-retry-${row.source_id}`} disabled={retry.isPending} className="px-2 py-1 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-50" onClick={() => {
          if (window.confirm("להוסיף את האירוע לתור ניסיון חוזר?")) {
            setRetryResult(null);
            retry.mutate({ sourceType: row.source_type, sourceId: row.source_id });
          }
        }}>ניסיון חוזר</button>
      )}
    </div> },
  ];

  return <div className="space-y-6" dir="rtl" data-testid="exchange-sync-content">
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-lg font-semibold">סנכרון לוח שנה עם Exchange</h2>
      <button type="button" className="px-3 py-1.5 rounded border border-gray-300 dark:border-gray-600" onClick={() => {
        void queryClient.invalidateQueries({ queryKey: ["exchange-sync-summary"] });
        void queryClient.invalidateQueries({ queryKey: ["exchange-sync-events"] });
      }}>רענון</button>
    </div>

    <section>
      <h3 className="text-sm font-semibold mb-2">מצב כללי</h3>
      {summary.isError ? <div data-testid="exchange-sync-summary-error" className="text-red-600">טעינת מצב הסנכרון נכשלה.</div>
        : summary.isLoading || !summary.data ? <div data-testid="exchange-sync-summary-loading" className="text-gray-500">טוען...</div>
          : <div data-testid="exchange-sync-summary" className="space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {countLabels.map(([key, label]) => <div key={key} data-testid={`exchange-sync-count-${key}`} className="rounded border border-gray-200 dark:border-gray-700 p-2"><div className="text-xs text-gray-500">{label}</div><div className="font-semibold">{summary.data.counts[key]}</div></div>)}
            </div>
            <div className="flex flex-wrap gap-3 text-sm">ניסיונות ב־24 השעות האחרונות: {recentLabels.map(([key, label]) => <span key={key} data-testid={`exchange-sync-recent-${key}`}>{label}: {summary.data.recent[key]}</span>)}</div>
            <div className="rounded border border-gray-200 dark:border-gray-700 p-3 text-sm space-y-1">
              <div data-testid="exchange-sync-worker">פעימות עובד הרקע: {formatTime(summary.data.worker_heartbeat_at)}</div>
              <div data-testid="exchange-sync-connection">חיבור Exchange: {summary.data.exchange_reachable === true ? "זמין" : summary.data.exchange_reachable === false ? "לא זמין" : "טרם נבדק"}{summary.data.latest_connection_error_category && <span className="text-xs text-gray-500"> ({summary.data.latest_connection_error_category})</span>}</div>
              <div>בדיקה אחרונה: {formatTime(summary.data.last_probe_at)}</div>
              <div>ניסיון חיבור אחרון: {formatTime(summary.data.last_connection_attempt_at)}</div>
              <div>קשר מוצלח אחרון: {formatTime(summary.data.last_successful_contact_at)}</div>
              {summary.data.latest_connection_error && <div className="text-red-600">{summary.data.latest_connection_error}</div>}
              {summary.data.global_backoff_until && <div data-testid="exchange-sync-backoff">השהיה משותפת עד {formatTime(summary.data.global_backoff_until)}</div>}
            </div>
          </div>}
    </section>

    <section>
      <h3 className="text-sm font-semibold mb-2">אירועים</h3>
      {events.isError ? <div data-testid="exchange-sync-events-error" className="text-red-600">טעינת האירועים נכשלה.</div>
        : events.isLoading || !events.data ? <div data-testid="exchange-sync-events-loading" className="text-gray-500">טוען...</div>
          : events.data.items.length === 0 ? <div data-testid="exchange-sync-events-empty" className="text-gray-500">אין אירועים להצגה.</div>
            : <DataTable columns={columns} data={events.data.items} testId="exchange-sync-events-table" emptyMessage="אין אירועים להצגה." />}
      {events.data && <div className="flex items-center gap-3 mt-2 text-sm">
        <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>הקודם</button>
        <span>{offset + 1}–{Math.min(offset + 25, events.data.total)} מתוך {events.data.total}</span>
        <button type="button" disabled={offset + 25 >= events.data.total} onClick={() => setOffset(offset + 25)}>הבא</button>
      </div>}
      {retryResult && <div data-testid="exchange-sync-retry-result" className="text-sm text-green-700 dark:text-green-300 mt-2">{retryResult}</div>}
      {retry.isError && <div data-testid="exchange-sync-retry-error" className="text-sm text-red-600 mt-2">הוספה לתור נכשלה.</div>}
    </section>

    {history && <div role="dialog" aria-modal="true" data-testid="exchange-sync-history-detail" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="max-w-lg w-full rounded bg-white dark:bg-gray-900 p-4 space-y-3">
        <div className="flex justify-between"><h3 className="font-semibold">היסטוריית ניסיונות</h3><button type="button" aria-label="סגירה" onClick={() => setHistory(null)}>×</button></div>
        {history.recent_attempts.length === 0 ? <p>אין ניסיונות קודמים.</p> : <ul className="space-y-2">{history.recent_attempts.map((attempt, index) => <li key={`${attempt.attempted_at}-${index}`} className="border-b border-gray-200 dark:border-gray-700 pb-2">{formatTime(attempt.attempted_at)} · {attempt.outcome}{attempt.error && ` · ${attempt.error}`}</li>)}</ul>}
      </div>
    </div>}
  </div>;
}
