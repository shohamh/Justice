import { Fragment, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ExcludedRangeCandidate, RangeAssignment, RangeCandidate, RangeEvent, batchAssignRange, getRangeCandidates, removeRangeAssignment, updateRangeAssignmentReason } from "../../api/ranges";
import { SoldierDTO } from "../../api/soldiers";
import { EventDetailModal } from "../planning";
import TableSearchInput from "../TableSearchInput";
import { translateApiError } from "../../utils/translateApiError";
import { formatDate } from "../../utils/formatDate";

export interface RangeEditAssignmentsModalProps {
  open: boolean;
  event: RangeEvent;
  soldiers: SoldierDTO[];
  canManage: boolean;
  onClose: () => void;
  onChanged: () => Promise<void>;
}

const REASON_LABEL: Record<string, string> = {
  manual: "שיבוץ ידני",
  qualified: "כשירות תקפה למטווח",
  duty_priority: "עדיפות לפי תורנות קרובה",
  reserve_duty_priority: "עדיפות לפי תורנות רזרבה קרובה",
  weapon_duty_priority: "עדיפות לפי מטווח הנשק הקרוב",
  available_and_balanced: "זמינות ואיזון הסגל",
  legacy: "שיבוץ קיים",
};

function matchesQuery(name: string, personalNumber: string | undefined, query: string): boolean {
  if (!query.trim()) return true;
  const q = query.trim().toLowerCase();
  return name.toLowerCase().includes(q) || !!personalNumber?.toLowerCase().includes(q);
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
  const [excludedCandidates, setExcludedCandidates] = useState<ExcludedRangeCandidate[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [primarySelected, setPrimarySelected] = useState<Set<string>>(new Set());
  const [reserveSelected, setReserveSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [primaryPanelOpen, setPrimaryPanelOpen] = useState(true);
  const [reservePanelOpen, setReservePanelOpen] = useState(true);
  const [summarySearch, setSummarySearch] = useState("");
  const [primarySearch, setPrimarySearch] = useState("");
  const [reserveSearch, setReserveSearch] = useState("");

  useEffect(() => {
    setAssignments(event.assignments);
    setError("");
  }, [event]);

  const name = (id: string) => soldiers.find(s => s.id === id)?.full_name ?? id;
  const personalNumber = (id: string) => soldiers.find(s => s.id === id)?.personal_number;

  const primary = useMemo(() => assignments.filter(a => !a.is_reserve), [assignments]);
  const reserves = useMemo(() => assignments.filter(a => a.is_reserve), [assignments]);
  const editable = open && canManage && event.status === "planned";
  const actionClass = "rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50";

  useEffect(() => {
    if (!editable) return;
    setCandidatesLoading(true);
    getRangeCandidates(event.id)
      .then(({ candidates, excluded }) => { setRangeCandidates(candidates); setExcludedCandidates(excluded); })
      .catch(() => { setRangeCandidates([]); setExcludedCandidates([]); })
      .finally(() => setCandidatesLoading(false));
  }, [event.id, editable]);

  const pendingPrimaries = useMemo(() => rangeCandidates.filter(c => primarySelected.has(c.soldier_id)), [rangeCandidates, primarySelected]);
  const pendingReserves = useMemo(() => rangeCandidates.filter(c => reserveSelected.has(c.soldier_id)), [rangeCandidates, reserveSelected]);

  // Slots remaining must account for not-yet-saved (pending) selections too —
  // otherwise auto-select and its button stay enabled past capacity once the
  // user has already picked enough candidates but hasn't hit "save" yet.
  const primarySlotsLeft = Math.max(0, event.required_count - primary.length - pendingPrimaries.length);
  const reserveSlotsLeft = Math.max(0, event.reserve_count - reserves.length - pendingReserves.length);
  const primaryFull = primary.length + pendingPrimaries.length >= event.required_count;
  const reserveFull = reserves.length + pendingReserves.length >= event.reserve_count;

  const primaryCandidates = useMemo(
    () => rangeCandidates.filter(c => !reserveSelected.has(c.soldier_id)),
    [rangeCandidates, reserveSelected]
  );

  const reserveCandidates = useMemo(
    () => rangeCandidates.filter(c => !primarySelected.has(c.soldier_id)),
    [rangeCandidates, primarySelected]
  );

  function togglePrimary(id: string) {
    if (!primarySelected.has(id) && primarySlotsLeft === 0) {
      setError(text("ranges.errors.primary_full", "אין מקומות פנויים לשיבוץ ראשי — בטלו שיבוץ קיים כדי להוסיף"));
      return;
    }
    setError("");
    setPrimarySelected(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });
    setReserveSelected(prev => { if (!prev.has(id)) return prev; const next = new Set(prev); next.delete(id); return next; });
  }

  function toggleReserve(id: string) {
    if (!reserveSelected.has(id) && reserveSlotsLeft === 0) {
      setError(text("ranges.errors.reserve_full", "אין מקומות פנויים לרזרבה — בטלו שיבוץ קיים כדי להוסיף"));
      return;
    }
    setError("");
    setReserveSelected(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });
    setPrimarySelected(prev => { if (!prev.has(id)) return prev; const next = new Set(prev); next.delete(id); return next; });
  }

  function autoSelectPrimary() {
    const top = primaryCandidates.slice(0, primarySlotsLeft).map(c => c.soldier_id);
    setPrimarySelected(new Set(top));
  }

  function autoSelectReserve() {
    const top = reserveCandidates.slice(0, reserveSlotsLeft).map(c => c.soldier_id);
    setReserveSelected(new Set(top));
  }

  const totalSelected = primarySelected.size + reserveSelected.size;

  async function saveSelection() {
    if (!editable || saving || totalSelected === 0) return;
    if (primary.length + pendingPrimaries.length > event.required_count) {
      setError(text("ranges.errors.primary_full", "אין מקומות פנויים לשיבוץ ראשי — בטלו שיבוץ קיים כדי להוסיף"));
      return;
    }
    if (reserves.length + pendingReserves.length > event.reserve_count) {
      setError(text("ranges.errors.reserve_full", "אין מקומות פנויים לרזרבה — בטלו שיבוץ קיים כדי להוסיף"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      const created = await batchAssignRange(event.id, { primaries: [...primarySelected], reserves: [...reserveSelected] });
      setAssignments(current => [...current, ...created]);
      setPrimarySelected(new Set());
      setReserveSelected(new Set());
      await getRangeCandidates(event.id)
        .then(({ candidates, excluded }) => { setRangeCandidates(candidates); setExcludedCandidates(excluded); })
        .catch(() => { setRangeCandidates([]); setExcludedCandidates([]); });
      await onChanged();
    } catch (err) {
      setError(translateApiError(err, t, text("ranges.errors.save_assignments", "שמירת השיבוצים נכשלה")));
    } finally {
      setSaving(false);
    }
  }

  async function remove(assignmentId: string) {
    if (!editable || removing) return;
    const reason = window.prompt("סיבת ההסרה:");
    if (!reason || !reason.trim()) return;
    setRemoving(assignmentId);
    setError("");
    try {
      await removeRangeAssignment(event.id, assignmentId, reason.trim());
      setAssignments(current => current.filter(a => a.id !== assignmentId));
      await getRangeCandidates(event.id)
        .then(({ candidates, excluded }) => { setRangeCandidates(candidates); setExcludedCandidates(excluded); })
        .catch(() => { setRangeCandidates([]); setExcludedCandidates([]); });
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
    return text(key, REASON_LABEL[code] ?? REASON_LABEL.legacy);
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

  const hasCurrentOrPending = primary.length > 0 || reserves.length > 0 || pendingPrimaries.length > 0 || pendingReserves.length > 0;

  const summaryRowVisible = (id: string) => matchesQuery(name(id), personalNumber(id), summarySearch);

  function renderAssignmentRow(a: RangeAssignment, typeLabel: string, rowClass: string) {
    const isEditing = editingReason === a.id;
    return (
      <Fragment key={a.id}>
        <tr className={`border-t dark:border-gray-600 ${rowClass}`}>
          <td className="p-2">{name(a.soldier_id)}</td>
          <td className="p-2 text-gray-500 dark:text-gray-400">{typeLabel}</td>
          <td className="p-2">{isEditing ? <span className="text-gray-400">{text("ranges.editing", "עריכה...")}</span> : reasonFor(a)}</td>
          <td className="p-2 text-center whitespace-nowrap">
            {editable && !isEditing && (
              <button
                type="button"
                data-testid={`edit-assignment-reason-${a.id}`}
                onClick={() => { setEditingReason(a.id); setReasonText(a.assignment_reason_text ?? reasonFor(a)); }}
                title={text("ranges.edit_reason", "עריכת סיבה")}
                aria-label={text("ranges.edit_reason", "עריכת סיבה")}
                className="inline-flex h-7 w-7 items-center justify-center rounded border border-gray-300 text-sm text-gray-600 hover:border-gray-400 hover:bg-gray-100 dark:border-gray-500 dark:text-gray-300 dark:hover:bg-gray-600"
              >✏️</button>
            )}
            {editable && (
              <button
                type="button"
                data-testid={`remove-assignment-${a.id}`}
                disabled={removing !== null}
                onClick={() => void remove(a.id)}
                title={text("ranges.remove", "הסר")}
                aria-label={text("ranges.remove", "הסר")}
                className="inline-flex h-7 w-7 items-center justify-center rounded border border-red-200 text-sm text-red-600 hover:bg-red-50 disabled:opacity-40 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950 mr-1"
              >{removing === a.id ? "…" : "✕"}</button>
            )}
          </td>
        </tr>
        {isEditing && (
          <tr className="border-t dark:border-gray-600 bg-blue-50 dark:bg-blue-950/30">
            <td colSpan={4} className="p-2">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  aria-label={text("ranges.assignment_reason_label", "סיבת השיבוץ")}
                  value={reasonText}
                  onChange={e => setReasonText(e.target.value)}
                  className="min-w-0 flex-1 rounded border px-2 py-1 text-xs text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                />
                <div className="flex gap-1">
                  <button type="button" data-testid={`save-assignment-reason-${a.id}`} disabled={savingReason === a.id || !reasonText.trim()} onClick={() => void saveReason(a)} className={`${actionClass} border-blue-600 bg-blue-600 text-white`}>{text("ranges.save", "שמור")}</button>
                  <button type="button" onClick={() => setEditingReason(null)} className={`${actionClass} border-gray-300 text-gray-700 dark:border-gray-500 dark:text-gray-100`}>{text("ranges.cancel_selection", "בטל")}</button>
                </div>
              </div>
            </td>
          </tr>
        )}
      </Fragment>
    );
  }

  return <EventDetailModal open={open} title={text("ranges.edit_assignments", "עריכת שיבוצים")} subtitle={`${event.location} · ${formatDate(event.date)}`} onClose={onClose}>
    <div className="overflow-y-auto flex-1 space-y-5">
      {/* Summary table — current + pending */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <p className="text-sm font-medium">
            {text("ranges.assignments_label", "שיבוצים")}
            <span className="text-xs font-normal text-gray-500 dark:text-gray-400 mr-2">
              {primary.length + pendingPrimaries.length}/{event.required_count} {text("ranges.primary_short", "ראשיים")}
              {primaryFull && <span data-testid="range-capacity-full"> · {text("ranges.full", "מלאה")}</span>}
              {event.reserve_count > 0 && <>
                {" · "}{reserves.length + pendingReserves.length}/{event.reserve_count} {text("ranges.reserve_short", "רזרבות")}
                {reserveFull && <span data-testid="range-capacity-full"> · {text("ranges.full", "מלאה")}</span>}
              </>}
            </span>
          </p>
          {hasCurrentOrPending && <div className="w-48"><TableSearchInput value={summarySearch} onChange={setSummarySearch} /></div>}
        </div>
        {!hasCurrentOrPending ? (
          <p className="text-xs text-gray-400 italic">{text("ranges.no_assignments", "אין שיבוצים עדיין")}</p>
        ) : (
          <div className="border dark:border-gray-600 rounded overflow-x-auto max-h-64 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 dark:bg-gray-700 sticky top-0">
                <tr>
                  <th className="text-right p-2 font-medium">{text("ranges.name_label", "שם")}</th>
                  <th className="text-right p-2 font-medium">{text("ranges.type_label", "סוג")}</th>
                  <th className="text-right p-2 font-medium">{text("ranges.assignment_reason_label", "סיבת השיבוץ")}</th>
                  <th className="p-2 w-24"></th>
                </tr>
              </thead>
              <tbody>
                {primary.filter(a => summaryRowVisible(a.soldier_id)).map(a => renderAssignmentRow(a, text("ranges.primary_short", "ראשי"), ""))}
                {pendingPrimaries.filter(c => matchesQuery(c.full_name, c.personal_number, summarySearch)).map(c => (
                  <tr key={c.soldier_id} className="border-t dark:border-gray-600 bg-indigo-50 dark:bg-indigo-950/40">
                    <td className="p-2 text-indigo-700 dark:text-indigo-300">{c.full_name}<span className="mr-2 text-xs text-indigo-400">{text("ranges.unsaved", "טרם נשמר")}</span></td>
                    <td className="p-2 text-indigo-500 dark:text-indigo-300">{text("ranges.primary_short", "ראשי")}</td>
                    <td className="p-2 text-indigo-400 dark:text-indigo-500">{REASON_LABEL[c.reason_code] ?? c.reason_code}</td>
                    <td className="p-2 text-center whitespace-nowrap">
                      <span className="inline-block h-7 w-7" />
                      <button
                        type="button"
                        onClick={() => togglePrimary(c.soldier_id)}
                        title={text("ranges.cancel_selection", "בטל בחירה")}
                        aria-label={text("ranges.cancel_selection", "בטל בחירה")}
                        className="mr-1 inline-flex h-7 w-7 items-center justify-center rounded border border-indigo-200 text-sm text-indigo-500 hover:bg-indigo-100 dark:border-indigo-800 dark:text-indigo-300 dark:hover:bg-indigo-900"
                      >✕</button>
                    </td>
                  </tr>
                ))}
                {reserves.filter(a => summaryRowVisible(a.soldier_id)).map(a => renderAssignmentRow(a, text("ranges.reserve_short", "רזרבה"), "bg-gray-50/50 dark:bg-gray-700/30"))}
                {pendingReserves.filter(c => matchesQuery(c.full_name, c.personal_number, summarySearch)).map(c => (
                  <tr key={c.soldier_id} className="border-t dark:border-gray-600 bg-indigo-50/50 dark:bg-indigo-950/20">
                    <td className="p-2 text-indigo-600 dark:text-indigo-300">{c.full_name}<span className="mr-2 text-xs text-indigo-300">{text("ranges.unsaved", "טרם נשמר")}</span></td>
                    <td className="p-2 text-indigo-400">{text("ranges.reserve_short", "רזרבה")}</td>
                    <td className="p-2 text-indigo-400 dark:text-indigo-500">{REASON_LABEL[c.reason_code] ?? c.reason_code}</td>
                    <td className="p-2 text-center whitespace-nowrap">
                      <span className="inline-block h-7 w-7" />
                      <button
                        type="button"
                        onClick={() => toggleReserve(c.soldier_id)}
                        title={text("ranges.cancel_selection", "בטל בחירה")}
                        aria-label={text("ranges.cancel_selection", "בטל בחירה")}
                        className="mr-1 inline-flex h-7 w-7 items-center justify-center rounded border border-indigo-200 text-sm text-indigo-500 hover:bg-indigo-100 dark:border-indigo-800 dark:text-indigo-300 dark:hover:bg-indigo-900"
                      >✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editable && <>
        {/* Add primaries */}
        <div className="border dark:border-gray-600 rounded">
          <button type="button" onClick={() => setPrimaryPanelOpen(v => !v)} className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700/50 rounded-t">
            <span>{primaryPanelOpen ? "▾" : "▸"}</span>
            <span>{text("ranges.candidates_primary", "מועמדים — ראשי")}</span>
            <span className="text-xs font-normal text-gray-500 dark:text-gray-400">{primarySlotsLeft > 0 ? `נותרו ${primarySlotsLeft} מקומות` : text("ranges.full", "מלאה")}</span>
            {primarySelected.size > 0 && <span className="mr-auto text-xs text-indigo-600 dark:text-indigo-300">{primarySelected.size} נבחרו</span>}
          </button>
          {primaryPanelOpen && (
            <div className="border-t dark:border-gray-600 p-2 space-y-2">
              {primarySlotsLeft === 0 && (
                <p className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-400">
                  {text("ranges.errors.primary_full", "אין מקומות פנויים לשיבוץ ראשי — בטלו שיבוץ קיים כדי להוסיף")}
                </p>
              )}
              <div className="flex items-center gap-2">
                <div className="flex-1"><TableSearchInput value={primarySearch} onChange={setPrimarySearch} /></div>
                <div className="flex gap-2 text-xs whitespace-nowrap">
                  <button type="button" data-testid="range-auto-select-primary" onClick={autoSelectPrimary} disabled={primarySlotsLeft === 0 || primaryCandidates.length === 0} className="text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-40">{text("ranges.auto_select", "בחר אוטומטית")}</button>
                  <button type="button" onClick={() => setPrimarySelected(new Set())} className="text-blue-600 dark:text-blue-400 hover:underline">{text("ranges.cancel_selection", "בטל")}</button>
                </div>
              </div>
              <CandidateTable
                candidates={primaryCandidates.filter(c => matchesQuery(c.full_name, c.personal_number, primarySearch))}
                selected={primarySelected}
                onToggle={togglePrimary}
                testIdPrefix="candidate-checkbox"
                full={primarySlotsLeft === 0}
                loading={candidatesLoading}
                excluded={excludedCandidates}
              />
            </div>
          )}
        </div>

        {/* Add reserves */}
        <div className="border dark:border-gray-600 rounded">
          <button type="button" onClick={() => setReservePanelOpen(v => !v)} className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700/50 rounded-t">
            <span>{reservePanelOpen ? "▾" : "▸"}</span>
            <span>{text("ranges.candidates_reserve", "מועמדים — רזרבה")}</span>
            {event.reserve_count > 0 && <span className="text-xs font-normal text-gray-500 dark:text-gray-400">{reserveSlotsLeft > 0 ? `נותרו ${reserveSlotsLeft} מקומות` : text("ranges.full", "מלאה")}</span>}
            {reserveSelected.size > 0 && <span className="mr-auto text-xs text-indigo-600 dark:text-indigo-300">{reserveSelected.size} נבחרו</span>}
          </button>
          {reservePanelOpen && (
            <div className="border-t dark:border-gray-600 p-2 space-y-2">
              {event.reserve_count > 0 && reserveSlotsLeft === 0 && (
                <p className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-400">
                  {text("ranges.errors.reserve_full", "אין מקומות פנויים לרזרבה — בטלו שיבוץ קיים כדי להוסיף")}
                </p>
              )}
              <div className="flex items-center gap-2">
                <div className="flex-1"><TableSearchInput value={reserveSearch} onChange={setReserveSearch} /></div>
                <div className="flex gap-2 text-xs whitespace-nowrap">
                  <button type="button" data-testid="range-auto-select-reserve" onClick={autoSelectReserve} disabled={reserveSlotsLeft === 0 || reserveCandidates.length === 0} className="text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-40">{text("ranges.auto_select", "בחר אוטומטית")}</button>
                  <button type="button" onClick={() => setReserveSelected(new Set())} className="text-blue-600 dark:text-blue-400 hover:underline">{text("ranges.cancel_selection", "בטל")}</button>
                </div>
              </div>
              <CandidateTable
                candidates={reserveCandidates.filter(c => matchesQuery(c.full_name, c.personal_number, reserveSearch))}
                selected={reserveSelected}
                onToggle={toggleReserve}
                testIdPrefix="reserve-candidate-checkbox"
                full={reserveSlotsLeft === 0}
                loading={candidatesLoading}
                excluded={excludedCandidates}
              />
            </div>
          )}
        </div>

        {error && <p role="alert" className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        <button type="button" data-testid="save-assignments" disabled={saving || totalSelected === 0} onClick={() => void saveSelection()} className={`${actionClass} border-green-600 bg-green-600 text-white`}>
          {saving ? text("ranges.saving", "שומר...") : `${text("ranges.save_assignments", "שמור שיבוצים")}${totalSelected > 0 ? ` (${totalSelected})` : ""}`}
        </button>
      </>}

      <div className="flex justify-end border-t pt-3 dark:border-gray-600">
        <button type="button" onClick={onClose} className="rounded border px-3 py-1.5 text-sm dark:border-gray-600 dark:text-gray-100">{text("ranges.close", "סגור")}</button>
      </div>
    </div>
  </EventDetailModal>;
}

interface CandidateTableProps {
  candidates: RangeCandidate[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  testIdPrefix: string;
  full: boolean;
  loading: boolean;
  excluded: ExcludedRangeCandidate[];
}

function CandidateTable({ candidates, selected, onToggle, testIdPrefix, full, loading, excluded }: CandidateTableProps) {
  const { t } = useTranslation();
  return (
    <>
      <div className="border dark:border-gray-600 rounded overflow-x-auto max-h-64 overflow-y-auto">
        <table className="w-full text-xs">
        <thead className="bg-gray-50 dark:bg-gray-700 sticky top-0">
          <tr>
            <th className="p-2 w-8"></th>
            <th className="text-right p-2 font-medium">שם</th>
            <th className="text-right p-2 font-medium">מ&quot;א</th>
            <th className="text-right p-2 font-medium">תעדוף</th>
          </tr>
        </thead>
        <tbody>
          {candidates.length === 0 && (
            <tr><td colSpan={4} className="p-2 text-center text-gray-400 italic">{loading ? "טוען רשימת מועמדים..." : "אין מועמדים זמינים"}</td></tr>
          )}
          {candidates.map(c => {
            const isSelected = selected.has(c.soldier_id);
            const isDisabled = full && !isSelected;
            return (
              <tr
                key={c.soldier_id}
                className={`border-t dark:border-gray-600 ${isDisabled ? "opacity-40" : "hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"}`}
                onClick={() => !isDisabled && onToggle(c.soldier_id)}
              >
                <td className="p-2"><input type="checkbox" data-testid={`${testIdPrefix}-${c.soldier_id}`} checked={isSelected} disabled={isDisabled} onChange={() => onToggle(c.soldier_id)} onClick={e => e.stopPropagation()} /></td>
                <td className="p-2">
                  {c.full_name}
                  {c.conflict_warning && (
                    <span
                      title={c.conflict_warning}
                      aria-label={c.conflict_warning}
                      className="mr-1 text-amber-500 dark:text-amber-400"
                    >⚠️</span>
                  )}
                </td>
                <td className="p-2 text-gray-500 dark:text-gray-400" dir="ltr">{c.personal_number}</td>
                <td className="p-2 text-gray-500 dark:text-gray-400">
                  {c.explanation || (REASON_LABEL[c.reason_code] ?? c.reason_code)}
                  {c.conflict_warning && (
                    <span className="block text-amber-600 dark:text-amber-400">{c.conflict_warning}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
        </table>
      </div>
      {excluded.length > 0 && (
        <details className="mt-2 text-xs text-gray-500 dark:text-gray-400">
          <summary className="cursor-pointer">{t("ranges.excluded_summary", { count: excluded.length })}</summary>
          <ul className="mt-1 space-y-0.5">
            {excluded.map(candidate => (
              <li key={candidate.soldier_id}>{candidate.soldier_name}: {t(`ranges.excluded_reason.${candidate.reason}`)}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
