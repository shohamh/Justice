import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { RangeAssignment, RangeEvent, addRangeAssignment, autoAssignRange, confirmAllDrafts, confirmDraftAssignment, removeRangeAssignment, updateRangeAssignmentReason } from "../../api/ranges";
import { SoldierDTO } from "../../api/soldiers";
import { EventDetailModal } from "../planning";
import { translateApiError } from "../../utils/translateApiError";

export interface RangeEditAssignmentsModalProps {
  open: boolean;
  event: RangeEvent;
  soldiers: SoldierDTO[];
  canManage: boolean;
  onClose: () => void;
  onChanged: () => Promise<void>;
}

export default function RangeEditAssignmentsModal({ open, event, soldiers, canManage, onClose, onChanged }: RangeEditAssignmentsModalProps) {
  const { t } = useTranslation();
  const text = (key: string, fallback: string) => {
    const translated = t(key);
    return translated === key ? fallback : translated;
  };
  const [assignments, setAssignments] = useState(event.assignments);
  const [query, setQuery] = useState("");
  const [reserve, setReserve] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [confirmingAll, setConfirmingAll] = useState(false);
  const [autoAssigning, setAutoAssigning] = useState(false);
  const [shortfall, setShortfall] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [editingReason, setEditingReason] = useState<string | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [savingReason, setSavingReason] = useState<string | null>(null);

  useEffect(() => {
    setAssignments(event.assignments);
    setShortfall(null);
    setError("");
  }, [event]);

  const primary = useMemo(() => assignments.filter(a => !a.is_reserve), [assignments]);
  const reserves = useMemo(() => assignments.filter(a => a.is_reserve), [assignments]);
  const assignedIds = useMemo(() => new Set(assignments.map(a => a.soldier_id)), [assignments]);
  const candidates = useMemo(() => soldiers.filter(s => !assignedIds.has(s.id) && (!query.trim() || `${s.full_name} ${s.personal_number}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))), [assignedIds, query, soldiers]);
  const primaryFull = primary.length >= event.required_count;
  const reserveFull = reserves.length >= event.reserve_count;
  const editable = open && canManage && event.status === "planned";
  const actionClass = "rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50";

  async function add(soldier: SoldierDTO) {
    if (!editable || adding || (reserve ? reserveFull : primaryFull)) return;
    setAdding(soldier.id);
    setError("");
    try {
      const created = await addRangeAssignment(event.id, soldier.id, reserve);
      setAssignments(current => [...current, created]);
      await onChanged();
    } catch {
      setError("הוספת השיבוץ נכשלה");
    } finally {
      setAdding(null);
    }
  }

  async function remove(assignmentId: string) {
    if (!editable || removing) return;
    setRemoving(assignmentId);
    setError("");
    try {
      await removeRangeAssignment(event.id, assignmentId);
      setAssignments(current => current.filter(a => a.id !== assignmentId));
      await onChanged();
    } catch {
      setError("הסרת השיבוץ נכשלה");
    } finally {
      setRemoving(null);
    }
  }

  async function autoAssign() {
    if (!editable || autoAssigning) return;
    setAutoAssigning(true);
    setError("");
    try {
      const result = await autoAssignRange(event.id);
      setAssignments(current => [...current, ...result.created.filter(a => !current.some(existing => existing.id === a.id))]);
      setShortfall(result.shortfall || null);
      await onChanged();
    } catch {
      setError("השיבוץ האוטומטי נכשל");
    } finally {
      setAutoAssigning(false);
    }
  }

  async function confirmDraft(assignmentId: string) {
    if (!editable || confirming || confirmingAll) return;
    setConfirming(assignmentId);
    setError("");
    try {
      const confirmed = await confirmDraftAssignment(event.id, assignmentId);
      setAssignments(current => current.map(a => a.id === assignmentId ? confirmed : a));
      await onChanged();
    } catch {
      setError("אישור השיבוץ נכשל");
    } finally {
      setConfirming(null);
    }
  }

  async function confirmAll() {
    if (!editable || confirming || confirmingAll) return;
    setConfirmingAll(true);
    setError("");
    try {
      const confirmed = await confirmAllDrafts(event.id);
      setAssignments(current => confirmed.length > 0 ? current.map(a => confirmed.find(c => c.id === a.id) ?? a) : current.map(a => ({ ...a, is_draft: false })));
      await onChanged();
    } catch {
      setError("אישור השיבוצים נכשל");
    } finally {
      setConfirmingAll(false);
    }
  }

  function reasonFor(a: RangeAssignment) {
    if (a.assignment_reason_text) return a.assignment_reason_text;
    const code = a.assignment_reason_code ?? "legacy";
    const key = `ranges.assignment_reasons.${code}`;
    const fallbacks: Record<string, string> = { manual: "שיבוץ ידני", qualified: "כשירות תקפה למטווח", weapon_duty_priority: "עדיפות לפי מטווח הנשק הקרוב", available_and_balanced: "זמינות ואיזון הסגל", legacy: "שיבוץ קיים" };
    return text(key, fallbacks[code] ?? fallbacks.legacy);
  }

  async function saveReason(a: RangeAssignment) {
    if (!editable || savingReason || !reasonText.trim()) return;
    setSavingReason(a.id);
    setError("");
    try {
      const updated = await updateRangeAssignmentReason(event.id, a.id, a.assignment_reason_code ?? "manual", reasonText.trim());
      setAssignments(current => current.map(item => item.id === a.id ? updated : item));
      setEditingReason(null);
      await onChanged();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      const fallback = detail === "custom_reason_text_required" || detail === "assignment_reason_code_required"
        ? text(`errors.${detail}`, "יש למלא את סיבת השיבוץ")
        : text("ranges.errors.update_reason", "עדכון סיבת השיבוץ נכשל");
      setError(translateApiError(err, t, fallback));
    } finally {
      setSavingReason(null);
    }
  }

  const name = (id: string) => soldiers.find(s => s.id === id)?.full_name ?? id;
  const renderAssignment = (a: RangeAssignment) => (
    <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2 text-sm first:border-t-0 dark:border-gray-600">
      <span>{name(a.soldier_id)} {a.is_draft && <span data-testid={`draft-badge-${a.id}`} className="mr-2 rounded bg-indigo-100 px-1.5 py-0.5 text-xs text-indigo-700">טרם נשמר</span>}<span className="mr-2 text-xs text-gray-600 dark:text-gray-300">{text("ranges.assignment_reason_label", "סיבת השיבוץ")}: {reasonFor(a)}</span></span>
      {editable && <span className="flex gap-1">
        {editingReason === a.id ? <><input aria-label={text("ranges.assignment_reason_label", "סיבת השיבוץ")} value={reasonText} onChange={e => setReasonText(e.target.value)} className="rounded border px-1 text-xs dark:bg-gray-700" /><button type="button" data-testid={`save-assignment-reason-${a.id}`} disabled={savingReason === a.id || !reasonText.trim()} onClick={() => void saveReason(a)} className={`${actionClass} border-blue-600 bg-blue-600 text-white`}>{text("ranges.save", "שמור")}</button></> : <button type="button" data-testid={`edit-assignment-reason-${a.id}`} onClick={() => { setEditingReason(a.id); setReasonText(a.assignment_reason_text ?? reasonFor(a)); }} className={`${actionClass} border-gray-300 text-gray-700 dark:border-gray-500 dark:text-gray-100`}>{text("ranges.edit_reason", "עריכת סיבה")}</button>}
        {a.is_draft && <button type="button" data-testid={`confirm-draft-${a.id}`} disabled={confirming !== null || confirmingAll} onClick={() => void confirmDraft(a.id)} className={`${actionClass} border-green-600 bg-green-600 text-white`}>אשר</button>}
        <button type="button" data-testid={`remove-assignment-${a.id}`} disabled={removing !== null} onClick={() => void remove(a.id)} className={`${actionClass} border-red-200 text-red-700`}>{removing === a.id ? "..." : "הסר"}</button>
      </span>}
    </li>
  );

  return <EventDetailModal open={open} title="עריכת שיבוצים" subtitle={`${event.location} · ${event.date}`} onClose={onClose}>
    <div className="space-y-4">
      {error && <p role="alert" className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {shortfall !== null && <div className="rounded bg-amber-100 px-3 py-2 text-sm">לא נמצאו מספיק מועמדים — חסרים {shortfall} שיבוצים</div>}
      <section data-testid="range-primary-assignments" className="rounded border dark:border-gray-600"><h4 className="border-b px-3 py-2 text-sm font-semibold dark:border-gray-600">שיבוצים ראשיים <span className="font-normal text-gray-500">{primary.length}/{event.required_count} {primaryFull && <span data-testid="range-capacity-full">· מלאה</span>}</span></h4><ul>{primary.length ? primary.map(renderAssignment) : <li className="px-3 py-2 text-sm text-gray-500">אין שיבוצים</li>}</ul></section>
      <section data-testid="range-reserve-assignments" className="rounded border dark:border-gray-600"><h4 className="border-b px-3 py-2 text-sm font-semibold dark:border-gray-600">שיבוצי רזרבה <span className="font-normal text-gray-500">{reserves.length}/{event.reserve_count} {reserveFull && <span data-testid="range-capacity-full">· מלאה</span>}</span></h4><ul>{reserves.length ? reserves.map(renderAssignment) : <li className="px-3 py-2 text-sm text-gray-500">אין שיבוצי רזרבה</li>}</ul></section>
      {editable && <section className="space-y-2 rounded border p-3 dark:border-gray-600">
        <div className="flex flex-wrap gap-2"><button type="button" data-testid="range-auto-assign" disabled={autoAssigning || (primaryFull && reserveFull)} onClick={() => void autoAssign()} className={`${actionClass} border-blue-600 bg-blue-600 text-white`}>שיבוץ אוטומטי</button>{assignments.some(a => a.is_draft) && <button type="button" data-testid="range-confirm-all" disabled={confirming !== null || confirmingAll} onClick={() => void confirmAll()} className={`${actionClass} border-green-600 bg-green-600 text-white`}>אשר הכל</button>}</div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" data-testid="range-reserve-toggle" checked={reserve} onChange={e => setReserve(e.target.checked)} /> שיבוץ כרזרבה</label>
        <input data-testid="range-soldier-search" value={query} onChange={e => setQuery(e.target.value)} placeholder="חיפוש חייל" className="w-full rounded border p-2 text-sm dark:bg-gray-700" />
        <div className="max-h-40 overflow-y-auto">{candidates.map(s => <button key={s.id} type="button" data-testid={`add-soldier-${s.id}`} disabled={adding !== null || (reserve ? reserveFull : primaryFull)} onClick={() => void add(s)} className="block w-full border-t p-2 text-right text-sm hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:hover:bg-gray-700">{adding === s.id ? "מוסיף..." : `${s.full_name} (${s.personal_number})`}</button>)}{candidates.length === 0 && <p className="p-2 text-sm text-gray-500">אין חיילים זמינים</p>}</div>
      </section>}
      <div className="flex justify-end border-t pt-3 dark:border-gray-600"><button type="button" onClick={onClose} className="rounded border px-3 py-1.5 text-sm dark:border-gray-600">סגור</button></div>
    </div>
  </EventDetailModal>;
}
