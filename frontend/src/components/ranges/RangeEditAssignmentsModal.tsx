import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { RangeAssignment, RangeCandidate, RangeEvent, batchAssignRange, getRangeCandidates, removeRangeAssignment, updateRangeAssignmentReason } from "../../api/ranges";
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
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [editingReason, setEditingReason] = useState<string | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [savingReason, setSavingReason] = useState<string | null>(null);
  const [rangeCandidates, setRangeCandidates] = useState<RangeCandidate[]>([]);
  const [primarySelected, setPrimarySelected] = useState<Set<string>>(new Set());
  const [reserveSelected, setReserveSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setAssignments(event.assignments);
    setError("");
  }, [event]);

  const primary = useMemo(() => assignments.filter(a => !a.is_reserve), [assignments]);
  const reserves = useMemo(() => assignments.filter(a => a.is_reserve), [assignments]);
  const primaryFull = primary.length >= event.required_count;
  const reserveFull = reserves.length >= event.reserve_count;
  const editable = open && canManage && event.status === "planned";
  const actionClass = "rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50";

  useEffect(() => {
    if (!editable) return;
    getRangeCandidates(event.id).then(setRangeCandidates).catch(() => setRangeCandidates([]));
  }, [event.id, editable]);

  const primarySlotsLeft = Math.max(0, event.required_count - primary.length);
  const reserveSlotsLeft = Math.max(0, event.reserve_count - reserves.length);
  const unblockedCandidates = useMemo(() => rangeCandidates.filter(c => !c.blocked), [rangeCandidates]);

  function toggleCandidate(id: string, isReserve: boolean) {
    const setSel = isReserve ? setReserveSelected : setPrimarySelected;
    setSel(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });
  }

  function autoSelectPrimary() {
    const top = unblockedCandidates.filter(c => !reserveSelected.has(c.soldier_id)).slice(0, primarySlotsLeft).map(c => c.soldier_id);
    setPrimarySelected(new Set(top));
  }

  function autoSelectReserve() {
    const top = unblockedCandidates.filter(c => !primarySelected.has(c.soldier_id)).slice(0, reserveSlotsLeft).map(c => c.soldier_id);
    setReserveSelected(new Set(top));
  }

  async function saveSelection() {
    if (!editable || saving || (primarySelected.size === 0 && reserveSelected.size === 0)) return;
    setSaving(true);
    setError("");
    try {
      const created = await batchAssignRange(event.id, { primaries: [...primarySelected], reserves: [...reserveSelected] });
      setAssignments(current => [...current, ...created]);
      setPrimarySelected(new Set());
      setReserveSelected(new Set());
      await getRangeCandidates(event.id).then(setRangeCandidates).catch(() => setRangeCandidates([]));
      await onChanged();
    } catch {
      setError(text("ranges.errors.save_assignments", "שמירת השיבוצים נכשלה"));
    } finally {
      setSaving(false);
    }
  }

  async function remove(assignmentId: string) {
    if (!editable || removing) return;
    setRemoving(assignmentId);
    setError("");
    try {
      await removeRangeAssignment(event.id, assignmentId);
      setAssignments(current => current.filter(a => a.id !== assignmentId));
      await getRangeCandidates(event.id).then(setRangeCandidates).catch(() => setRangeCandidates([]));
      await onChanged();
    } catch {
      setError(text("ranges.errors.remove_assignment", "הסרת השיבוץ נכשלה"));
    } finally {
      setRemoving(null);
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
      <span>{name(a.soldier_id)} <span className="mr-2 text-xs text-gray-600 dark:text-gray-300">{text("ranges.assignment_reason_label", "סיבת השיבוץ")}: {reasonFor(a)}</span></span>
      {editable && <span className="flex gap-1">
        {editingReason === a.id ? <><input aria-label={text("ranges.assignment_reason_label", "סיבת השיבוץ")} value={reasonText} onChange={e => setReasonText(e.target.value)} className="rounded border px-1 text-xs text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100" /><button type="button" data-testid={`save-assignment-reason-${a.id}`} disabled={savingReason === a.id || !reasonText.trim()} onClick={() => void saveReason(a)} className={`${actionClass} border-blue-600 bg-blue-600 text-white`}>{text("ranges.save", "שמור")}</button></> : <button type="button" data-testid={`edit-assignment-reason-${a.id}`} onClick={() => { setEditingReason(a.id); setReasonText(a.assignment_reason_text ?? reasonFor(a)); }} className={`${actionClass} border-gray-300 text-gray-700 dark:border-gray-500 dark:text-gray-100`}>{text("ranges.edit_reason", "עריכת סיבה")}</button>}
        <button type="button" data-testid={`remove-assignment-${a.id}`} disabled={removing !== null} onClick={() => void remove(a.id)} className={`${actionClass} border-red-200 text-red-700`}>{removing === a.id ? "..." : text("ranges.remove", "הסר")}</button>
      </span>}
    </li>
  );

  return <EventDetailModal open={open} title={text("ranges.edit_assignments", "עריכת שיבוצים")} subtitle={`${event.location} · ${event.date}`} onClose={onClose}>
    <div className="space-y-4">
      {error && <p role="alert" className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <section data-testid="range-primary-assignments" className="rounded border dark:border-gray-600"><h4 className="border-b px-3 py-2 text-sm font-semibold dark:border-gray-600">{text("ranges.primary_assignments", "שיבוצים ראשיים")} <span className="font-normal text-gray-500">{primary.length}/{event.required_count} {primaryFull && <span data-testid="range-capacity-full">· {text("ranges.full", "מלאה")}</span>}</span></h4><ul>{primary.length ? primary.map(renderAssignment) : <li className="px-3 py-2 text-sm text-gray-500">{text("ranges.no_assignments", "אין שיבוצים")}</li>}</ul></section>
      <section data-testid="range-reserve-assignments" className="rounded border dark:border-gray-600"><h4 className="border-b px-3 py-2 text-sm font-semibold dark:border-gray-600">{text("ranges.reserve_assignments", "שיבוצי רזרבה")} <span className="font-normal text-gray-500">{reserves.length}/{event.reserve_count} {reserveFull && <span data-testid="range-capacity-full">· {text("ranges.full", "מלאה")}</span>}</span></h4><ul>{reserves.length ? reserves.map(renderAssignment) : <li className="px-3 py-2 text-sm text-gray-500">{text("ranges.no_reserve_assignments", "אין שיבוצי רזרבה")}</li>}</ul></section>
      {editable && <section className="space-y-3 rounded border p-3 dark:border-gray-600">
        <div className="flex items-center justify-between"><h4 className="text-sm font-semibold">{text("ranges.candidates_primary", "מועמדים — ראשי")}</h4><button type="button" data-testid="range-auto-select-primary" disabled={primarySlotsLeft === 0} onClick={autoSelectPrimary} className={`${actionClass} border-blue-600 bg-blue-600 text-white`}>{text("ranges.auto_select", "בחר אוטומטית")}</button></div>
        <div className="max-h-32 overflow-y-auto">{rangeCandidates.map(c => <label key={`p-${c.soldier_id}`} className="flex items-center gap-2 border-t p-1.5 text-sm dark:border-gray-600"><input type="checkbox" data-testid={`candidate-checkbox-${c.soldier_id}`} disabled={c.blocked || reserveSelected.has(c.soldier_id)} checked={primarySelected.has(c.soldier_id)} onChange={() => toggleCandidate(c.soldier_id, false)} />{c.full_name}{c.blocked && <span className="text-xs text-gray-400">({c.blocked_reason})</span>}</label>)}</div>
        <div className="flex items-center justify-between"><h4 className="text-sm font-semibold">{text("ranges.candidates_reserve", "מועמדים — רזרבה")}</h4><button type="button" data-testid="range-auto-select-reserve" disabled={reserveSlotsLeft === 0} onClick={autoSelectReserve} className={`${actionClass} border-blue-600 bg-blue-600 text-white`}>{text("ranges.auto_select", "בחר אוטומטית")}</button></div>
        <div className="max-h-32 overflow-y-auto">{rangeCandidates.map(c => <label key={`r-${c.soldier_id}`} className="flex items-center gap-2 border-t p-1.5 text-sm dark:border-gray-600"><input type="checkbox" data-testid={`reserve-candidate-checkbox-${c.soldier_id}`} disabled={c.blocked || primarySelected.has(c.soldier_id)} checked={reserveSelected.has(c.soldier_id)} onChange={() => toggleCandidate(c.soldier_id, true)} />{c.full_name}{c.blocked && <span className="text-xs text-gray-400">({c.blocked_reason})</span>}</label>)}</div>
        <button type="button" data-testid="save-assignments" disabled={saving || (primarySelected.size === 0 && reserveSelected.size === 0)} onClick={() => void saveSelection()} className={`${actionClass} border-green-600 bg-green-600 text-white`}>{saving ? text("ranges.saving", "שומר...") : text("ranges.save_assignments", "שמור שיבוצים")}</button>
      </section>}
      <div className="flex justify-end border-t pt-3 dark:border-gray-600"><button type="button" onClick={onClose} className="rounded border px-3 py-1.5 text-sm dark:border-gray-600 dark:text-gray-100">{text("ranges.close", "סגור")}</button></div>
    </div>
  </EventDetailModal>;
}
