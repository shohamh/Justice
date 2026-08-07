import { ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { RangeAssignment, RangeEvent, RangeExcusalRequest } from "../../api/ranges";
import { RosterSection } from "../planning";
import RangeAttendancePanel from "./RangeAttendancePanel";
import { ATTENDANCE_STATUS_LABELS } from "../../utils/rangeLabels";

interface Props {
  event: RangeEvent;
  canManage: boolean;
  canEditAttendance?: boolean;
  userId?: string;
  soldierName: (id: string) => string;
  excusalRequests?: RangeExcusalRequest[];
  onExcuse: (id: string, reason: string) => Promise<void>;
  onDecide: (id: string, approve: boolean) => Promise<void>;
  onAttendance: () => void;
  actions?: ReactNode;
}

export default function RangeDetailContent(p: Props) {
  const { t } = useTranslation();
  const text = (key: string, fallback: string) => {
    const translated = t(key);
    return translated === key ? fallback : translated;
  };
  const { event } = p;
  const primary = event.assignments.filter(a => !a.is_reserve);
  const reserve = event.assignments.filter(a => a.is_reserve);
  const [excuseId, setExcuseId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const future = event.date > new Date().toISOString().slice(0, 10);
  const selfAssignment = event.assignments.find(a => future && !a.is_draft && a.soldier_id === p.userId);
  const actionClass = "rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50";

  const row = (a: RangeAssignment) => ({ id: a.id, soldierId: a.soldier_id, soldierName: p.soldierName(a.soldier_id), isDraft: a.is_draft, status: ATTENDANCE_STATUS_LABELS[a.attendance_status] ?? a.attendance_status });

  return <div className="space-y-4" data-testid="range-detail-content">
    {p.actions}
    {selfAssignment && <section className="flex flex-wrap items-center gap-2" data-testid="range-self-excusal-action"><button type="button" onClick={() => { setExcuseId(selfAssignment.id); setReason(""); }} className={`${actionClass} border-amber-300 text-amber-700`}>{text("ranges.self_excuse", "אני לא אוכל להגיע")}</button>{excuseId === selfAssignment.id && <span className="flex items-center gap-1"><input aria-label={text("ranges.self_excuse_reason", "סיבת היעדרות")} value={reason} onChange={e => setReason(e.target.value)} className="rounded border p-1 text-sm" /><button type="button" data-testid="submit-excuse-button" disabled={!reason.trim()} onClick={async () => { await p.onExcuse(selfAssignment.id, reason.trim()); setExcuseId(null); setReason(""); }} className={`${actionClass} border-blue-600 bg-blue-600 text-white`}>{text("ranges.send", "שלח")}</button></span>}</section>}
    <section data-testid="range-detail-information" className="rounded border bg-gray-50 p-4 text-sm text-gray-800 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"><h3 className="mb-2 text-sm font-semibold">מידע והנחיות</h3><div><b>הוראות הגעה:</b> {event.arrival_instructions || "—"}</div><div><b>איש קשר:</b> {event.contact_name || "—"} {event.contact_phone || ""}</div><div><b>הערות:</b> {event.notes || "—"}</div></section>
    <section data-testid="range-detail-roster" className="space-y-3"><h3 className="text-sm font-semibold">רשימת שיבוצים</h3><RosterSection kind="primary" assignments={primary.map(row)} count={event.required_count} assignmentActionRenderer={() => null} /><RosterSection kind="reserve" assignments={reserve.map(row)} count={event.reserve_count} assignmentActionRenderer={() => null} /></section>
    {p.excusalRequests && p.excusalRequests.length > 0 && <section data-testid="excusal-review-queue" className="space-y-2 rounded border p-4 dark:border-gray-600"><h3 className="text-sm font-semibold">בקשות היעדרות</h3>{p.excusalRequests.map(r => <div key={r.id} className="flex flex-wrap items-center gap-2 text-sm">{r.reason}{p.canManage && <><button type="button" data-testid={`approve-excusal-${r.id}`} onClick={() => p.onDecide(r.id, true)} className={`${actionClass} border-green-600 bg-green-600 text-white`}>אשר וקדם</button><button type="button" data-testid={`reject-excusal-${r.id}`} onClick={() => p.onDecide(r.id, false)} className={`${actionClass} border-red-200 text-red-700`}>דחה</button></>}</div>)}</section>}
    {p.canEditAttendance && event.date <= new Date().toISOString().slice(0, 10) && <section className="rounded border p-4 dark:border-gray-600"><RangeAttendancePanel eventId={event.id} assignments={event.assignments.filter(a => !a.is_draft)} soldierName={p.soldierName} onMarked={p.onAttendance} /></section>}
  </div>;
}
