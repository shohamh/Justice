import { ReactNode, useState } from "react";
import { RangeEvent, RangeAssignment, RangeExcusalRequest } from "../../api/ranges";
import { RosterSection } from "../planning";
import RangeAttendancePanel from "./RangeAttendancePanel";
import SoldierSearchAutocomplete from "../SoldierSearchAutocomplete";
import { SoldierDTO } from "../../api/soldiers";

interface Props { event: RangeEvent; canManage: boolean; userId?: string; soldierName: (id:string)=>string; soldiers?: SoldierDTO[]; excusalRequests?: RangeExcusalRequest[]; shortfall: number|null; onAutoAssign:()=>Promise<void>; onConfirmDraft:(id:string)=>Promise<void>; onConfirmAll:()=>Promise<void>; onAdd:(s:SoldierDTO|null,reserve:boolean)=>Promise<void>; onRemove:(id:string)=>Promise<void>; onExcuse:(id:string,reason:string)=>Promise<void>; onDecide:(id:string,approve:boolean)=>Promise<void>; onAttendance:()=>void; actions?: ReactNode; }

export default function RangeDetailContent(p: Props) {
  const { event } = p;
  const primary = event.assignments.filter(a => !a.is_reserve);
  const reserve = event.assignments.filter(a => a.is_reserve);
  const [picker, setPicker] = useState(false);
  const [reserveToggle, setReserveToggle] = useState(false);
  const [excuseId, setExcuseId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [confirmingAll, setConfirmingAll] = useState(false);
  const [autoAssigning, setAutoAssigning] = useState(false);
  const planned = event.status === "planned";
  const future = event.date > new Date().toISOString().slice(0, 10);
  const primaryFilled = event.primary_filled ?? primary.filter(a => !a.is_draft).length;
  const reserveFilled = event.reserve_filled ?? reserve.filter(a => !a.is_draft).length;
  const hasOpenSlot = primaryFilled < event.required_count || reserveFilled < event.reserve_count;

  const assignment = (a: RangeAssignment) => <>
    {planned && a.is_draft && p.canManage && <button type="button" data-testid="confirm-draft-button" disabled={confirming !== null || confirmingAll} onClick={async () => { setConfirming(a.id); try { await p.onConfirmDraft(a.id); } finally { setConfirming(null); } }}>אשר</button>}
    {p.canManage && planned && <button type="button" onClick={() => p.onRemove(a.id)} className="text-red-600">הסר</button>}
    {future && !a.is_draft && a.soldier_id === p.userId && <button type="button" data-testid={`excuse-button-${a.id}`} onClick={() => { setExcuseId(a.id); setReason(""); }}>בקש פטור</button>}
    {excuseId === a.id && <span><input aria-label="סיבת היעדרות" value={reason} onChange={e => setReason(e.target.value)} /><button type="button" data-testid="submit-excuse-button" disabled={!reason.trim()} onClick={async () => { await p.onExcuse(a.id, reason.trim()); setExcuseId(null); setReason(""); }}>שלח</button></span>}
  </>;
  const row = (a: RangeAssignment) => ({ id: a.id, soldierId: a.soldier_id, soldierName: p.soldierName(a.soldier_id), isDraft: a.is_draft, status: a.attendance_status });

  return <div className="space-y-3">
    {p.shortfall !== null && <div data-testid="shortfall-banner" className="rounded bg-amber-100 px-3 py-2">לא נמצאו מספיק מועמדים — חסרים {p.shortfall} שיבוצים</div>}
    {p.actions}
    <div className="rounded bg-gray-50 p-3 text-sm dark:bg-gray-700"><div><b>הוראות הגעה:</b> {event.arrival_instructions || "—"}</div><div><b>איש קשר:</b> {event.contact_name || "—"} {event.contact_phone || ""}</div><div><b>הערות:</b> {event.notes || "—"}</div></div>
    {p.canManage && planned && <div className="flex flex-wrap gap-2">{hasOpenSlot && <button data-testid="auto-assign-button" disabled={autoAssigning} onClick={async () => { setAutoAssigning(true); try { await p.onAutoAssign(); } finally { setAutoAssigning(false); } }}>שיבוץ אוטומטי</button>}{event.assignments.some(a => a.is_draft) && <button data-testid="confirm-all-button" disabled={confirming !== null || confirmingAll} onClick={async () => { setConfirmingAll(true); try { await p.onConfirmAll(); } finally { setConfirmingAll(false); } }}>אשר הכל</button>}<button data-testid="add-soldier-button" onClick={() => setPicker(true)}>הוסף חייל</button></div>}
    {picker && <div><label><input type="checkbox" data-testid="reserve-toggle" checked={reserveToggle} onChange={e => setReserveToggle(e.target.checked)} /> שיבוץ כרזרבה</label><SoldierSearchAutocomplete onSelect={s => { void p.onAdd(s, reserveToggle); setPicker(false); }} /></div>}
    <RosterSection kind="primary" assignments={primary.map(row)} count={event.required_count} assignmentActionRenderer={a => assignment(primary.find(x => x.id === a.id)!)} />
    <RosterSection kind="reserve" assignments={reserve.map(row)} count={event.reserve_count} assignmentActionRenderer={a => assignment(reserve.find(x => x.id === a.id)!)} />
    {p.excusalRequests && p.excusalRequests.length > 0 && <section data-testid="excusal-review-queue"><h3>בקשות היעדרות</h3>{p.excusalRequests.map(r => <div key={r.id}>{r.reason}{p.canManage && <><button data-testid={`approve-excusal-${r.id}`} onClick={() => p.onDecide(r.id, true)}>אשר וקדם</button><button data-testid={`reject-excusal-${r.id}`} onClick={() => p.onDecide(r.id, false)}>דחה</button></>}</div>)}</section>}
    {p.canManage && event.date <= new Date().toISOString().slice(0, 10) && <RangeAttendancePanel eventId={event.id} assignments={event.assignments.filter(a => !a.is_draft)} soldierName={p.soldierName} onMarked={p.onAttendance} />}
  </div>;
}
