import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyShift, assignBatch, removeShiftAssignment } from "../api/shifts";
import { DutyType } from "../api/dutyConfig";
import { ShiftCandidate, getShiftCandidates } from "../api/assignments";
import { CalendarShift, getCalendarShift } from "../api/calendar";
import { lastDutyDay } from "../utils/formatDate";
import { translateApiError } from "../utils/translateApiError";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  shift: DutyShift;
  dutyTypes: DutyType[];
  onSaved: () => void;
  onClose: () => void;
}

const BLOCKED_REASON_LABEL: Record<string, string> = {
  constraint: "אילוץ",
  assignment: "כבר משובץ",
};

function hierarchyDistance(pathA: string[], pathB: string[]): number {
  let common = 0;
  while (common < pathA.length && common < pathB.length && pathA[common] === pathB[common]) common++;
  return (pathA.length - common) + (pathB.length - common);
}

type ReserveCandidate = ShiftCandidate & { dist: number; coveringNames: string[]; coveringPrimarySoldierId: string | null };

export default function ShiftEditAssignmentsModal({ shift, dutyTypes, onSaved, onClose }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const [shiftDetail, setShiftDetail] = useState<CalendarShift | null>(null);
  const [candidates, setCandidates] = useState<ShiftCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [primarySelected, setPrimarySelected] = useState<Set<string>>(new Set());
  const [reserveSelected, setReserveSelected] = useState<Set<string>>(new Set());
  const [removing, setRemoving] = useState<string | null>(null);
  const [hasRemovals, setHasRemovals] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [primaryPanelOpen, setPrimaryPanelOpen] = useState(true);
  const [reservePanelOpen, setReservePanelOpen] = useState(true);

  const dutyTypeName = dutyTypes.find(d => d.id === shift.duty_type_id)?.name ?? "";

  useEffect(() => {
    setLoading(true);
    Promise.all([getCalendarShift(shift.id), getShiftCandidates(shift.id)])
      .then(([detail, cands]) => { setShiftDetail(detail); setCandidates(cands); })
      .catch(() => setError("שגיאה בטעינת נתונים"))
      .finally(() => setLoading(false));
  }, [shift.id]);

  // Current saved assignees
  const currentPrimaries = useMemo(
    () => shiftDetail?.assignees.filter(a => !a.is_reserve || a.called_up_from) ?? [],
    [shiftDetail]
  );
  const currentReserves = useMemo(
    () => shiftDetail?.assignees.filter(a => a.is_reserve && !a.called_up_from) ?? [],
    [shiftDetail]
  );

  // Pending (selected but not yet saved) candidates
  const pendingPrimaries = useMemo(
    () => candidates.filter(c => primarySelected.has(c.soldier_id)),
    [candidates, primarySelected]
  );
  const pendingReserves = useMemo(
    () => candidates.filter(c => reserveSelected.has(c.soldier_id)),
    [candidates, reserveSelected]
  );

  // Candidate lists — exclude already-assigned soldiers
  const assignedIds = useMemo(
    () => new Set(shiftDetail?.assignees.map(a => a.soldier_id) ?? []),
    [shiftDetail]
  );
  const unblockedCandidates = useMemo(
    () => candidates.filter(c => !c.blocked && !assignedIds.has(c.soldier_id)),
    [candidates, assignedIds]
  );
  const blockedCandidates = useMemo(
    () => candidates.filter(c => c.blocked && !assignedIds.has(c.soldier_id)),
    [candidates, assignedIds]
  );

  const primarySlotsLeft = Math.max(0, shift.required_count - (currentPrimaries.length - (shiftDetail?.assignees.filter(a => a.called_up_from).length ?? 0)));
  const totalReserveSlots = shift.reserve_count_override ?? shift.calculated_reserve_count ?? 0;
  const reserveSlotsLeft = Math.max(0, totalReserveSlots - currentReserves.length);

  const selectedPrimaryCandidates = useMemo(
    () => unblockedCandidates.filter(c => primarySelected.has(c.soldier_id)),
    [unblockedCandidates, primarySelected]
  );

  // All primaries for matching: already-assigned ones + newly selected candidates
  const allPrimariesForMatching = useMemo(() => {
    const existing = currentPrimaries.map(a => ({
      soldier_id: a.soldier_id,
      full_name: a.soldier_name,
      hierarchy_path_ids: a.hierarchy_path_ids,
    }));
    const selected = selectedPrimaryCandidates.map(c => ({
      soldier_id: c.soldier_id,
      full_name: c.full_name,
      hierarchy_path_ids: c.hierarchy_path_ids,
    }));
    return [...existing, ...selected];
  }, [currentPrimaries, selectedPrimaryCandidates]);

  const reserveCandidates = useMemo(() => {
    const available = candidates.filter(c => !primarySelected.has(c.soldier_id) && !assignedIds.has(c.soldier_id));
    const unblocked = available.filter(c => !c.blocked);
    const blocked = available.filter(c => c.blocked);

    if (allPrimariesForMatching.length === 0) {
      return {
        unblocked: unblocked
          .slice()
          .sort((a, b) => a.effort - b.effort)
          .map(c => ({ ...c, dist: Infinity, coveringNames: [], coveringPrimarySoldierId: null })),
        blocked,
      };
    }

    // Greedy bipartite matching: repeatedly pick the (primary, reserve) pair with
    // the smallest hierarchy distance, assign it, remove both, repeat.
    const remainingPrimaries = [...allPrimariesForMatching];
    const remainingReserves = unblocked.slice().sort((a, b) => a.effort - b.effort);
    const matched: ReserveCandidate[] = [];

    while (remainingPrimaries.length > 0 && remainingReserves.length > 0) {
      let bestDist = Infinity;
      let bestEffort = Infinity;
      let bestPrimaryIdx = -1;
      let bestReserveIdx = -1;

      for (let ri = 0; ri < remainingReserves.length; ri++) {
        for (let pi = 0; pi < remainingPrimaries.length; pi++) {
          const dist = hierarchyDistance(
            remainingReserves[ri].hierarchy_path_ids,
            remainingPrimaries[pi].hierarchy_path_ids,
          );
          const effort = remainingReserves[ri].effort;
          if (dist < bestDist || (dist === bestDist && effort < bestEffort)) {
            bestDist = dist;
            bestEffort = effort;
            bestPrimaryIdx = pi;
            bestReserveIdx = ri;
          }
        }
      }

      const reserve = remainingReserves[bestReserveIdx];
      const primary = remainingPrimaries[bestPrimaryIdx];
      matched.push({ ...reserve, dist: bestDist, coveringNames: [primary.full_name], coveringPrimarySoldierId: primary.soldier_id });
      remainingReserves.splice(bestReserveIdx, 1);
      remainingPrimaries.splice(bestPrimaryIdx, 1);
    }

    // Any leftover reserves (more reserves than primaries) sorted by effort
    const unmatched: ReserveCandidate[] = remainingReserves
      .sort((a, b) => a.effort - b.effort)
      .map(c => ({ ...c, dist: Infinity, coveringNames: [], coveringPrimarySoldierId: null }));

    return { unblocked: [...matched, ...unmatched], blocked };
  }, [candidates, primarySelected, assignedIds, allPrimariesForMatching]);

  function togglePrimary(id: string) {
    setPrimarySelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
    setReserveSelected(prev => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }

  function toggleReserve(id: string) {
    setReserveSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function autoSelectPrimary() {
    const top = unblockedCandidates.slice(0, primarySlotsLeft).map(c => c.soldier_id);
    setPrimarySelected(new Set(top));
    setReserveSelected(prev => { const next = new Set(prev); top.forEach(id => next.delete(id)); return next; });
  }

  function autoSelectReserves() {
    const limit = reserveSlotsLeft > 0 ? reserveSlotsLeft : reserveCandidates.unblocked.length;
    const top = reserveCandidates.unblocked.slice(0, limit).map(c => c.soldier_id);
    setReserveSelected(new Set(top));
  }

  async function handleRemove(assignmentId: string) {
    setRemoving(assignmentId);
    setError(null);
    try {
      await removeShiftAssignment(shift.id, assignmentId);
    } catch {
      setError("שגיאה בהסרת שיבוץ");
      setRemoving(null);
      return;
    }
    // Optimistic update so UI reflects the removal even if reload fails
    setHasRemovals(true);
    setShiftDetail(prev =>
      prev ? { ...prev, assignees: prev.assignees.filter(a => a.assignment_id !== assignmentId) } : prev
    );
    try {
      const [detail, cands] = await Promise.all([getCalendarShift(shift.id), getShiftCandidates(shift.id)]);
      setShiftDetail(detail);
      setCandidates(cands);
    } catch {
      // Reload failed — optimistic update already applied, candidates list may be stale
    }
    setRemoving(null);
  }

  async function handleSave() {
    if (totalSelected === 0) { onSaved(); return; }
    setSaving(true);
    setError(null);
    try {
      await assignBatch(shift.id, { primaries: [...primarySelected], reserves: [...reserveSelected] });
      onSaved();
    } catch (e: unknown) {
      setError(translateApiError(e, t, "שגיאה בשיבוץ"));
      setSaving(false);
    }
  }

  // assignment_id → soldier_name lookup for coverage column (saved assignments)
  const assigneeNameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const a of shiftDetail?.assignees ?? []) map[a.assignment_id] = a.soldier_name;
    return map;
  }, [shiftDetail]);

  // soldier_id of reserve candidate → names of primaries it would cover (from greedy matching)
  const reserveCandidateCoverage = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const c of reserveCandidates.unblocked) {
      map[c.soldier_id] = c.coveringNames;
    }
    return map;
  }, [reserveCandidates]);

  // soldier_id of primary → name of the pending reserve selected to cover them
  const pendingCoverageByPrimary = useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of reserveCandidates.unblocked) {
      if (reserveSelected.has(c.soldier_id) && c.coveringPrimarySoldierId) {
        map[c.coveringPrimarySoldierId] = c.full_name;
      }
    }
    return map;
  }, [reserveCandidates, reserveSelected]);

  const hasCurrentOrPending = currentPrimaries.length > 0 || currentReserves.length > 0 || pendingPrimaries.length > 0 || pendingReserves.length > 0;
  const totalSelected = primarySelected.size + reserveSelected.size;
  const canSave = totalSelected > 0 || hasRemovals;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-2xl w-full mx-4 flex flex-col max-h-[90vh]"
        dir="rtl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-4">
          <div>
            <h3 className="text-lg font-semibold">ערוך שיבוצים</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {dutyTypeName} · {shift.start_date} עד {lastDutyDay(shift.end_date)}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-lg">✕</button>
        </div>

        {loading && <p className="text-sm text-gray-500 py-6 text-center">טוען...</p>}

        {!loading && (
          <div className="overflow-y-auto flex-1 space-y-5">
            {/* Summary table — current + pending */}
            <div>
              <p className="text-sm font-medium mb-2">
                שיבוצים
                <span className="text-xs font-normal text-gray-500 dark:text-gray-400 mr-2">
                  {currentPrimaries.length + pendingPrimaries.length}/{shift.required_count} ראשיים
                  {totalReserveSlots > 0 && ` · ${currentReserves.length + pendingReserves.length}/${totalReserveSlots} רזרבות`}
                </span>
              </p>
              {!hasCurrentOrPending ? (
                <p className="text-xs text-gray-400 italic">אין שיבוצים עדיין</p>
              ) : (
                <div className="border dark:border-gray-600 rounded overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="bg-gray-50 dark:bg-gray-700">
                      <tr>
                        <th className="text-right p-2 font-medium">שם</th>
                        <th className="text-right p-2 font-medium">סוג</th>
                        <th className="text-right p-2 font-medium">כיסוי</th>
                        <th className="p-2 w-8"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {currentPrimaries.map(a => {
                        const pendingReserveName = pendingCoverageByPrimary[a.soldier_id];
                        const savedReserveName = a.reserve_assignment_id ? (assigneeNameById[a.reserve_assignment_id] ?? null) : null;
                        const coverCell = pendingReserveName
                          ? <span className="text-indigo-500 dark:text-indigo-300">{pendingReserveName} <span className="text-xs opacity-60">טרם נשמר</span></span>
                          : <span className="text-gray-400 dark:text-gray-500">{savedReserveName ?? "—"}</span>;
                        return (
                          <tr key={a.assignment_id} className="border-t dark:border-gray-600">
                            <td className="p-2">
                              {a.soldier_name}
                              {a.called_up_from && <span className="mr-2 text-amber-600 dark:text-amber-400">הוקפץ</span>}
                            </td>
                            <td className="p-2 text-gray-500 dark:text-gray-400">ראשי</td>
                            <td className="p-2">{coverCell}</td>
                            <td className="p-2 text-center">
                              <button type="button" onClick={() => handleRemove(a.assignment_id)}
                                disabled={removing === a.assignment_id}
                                className="text-red-500 hover:text-red-700 disabled:opacity-40 text-sm leading-none" title="הסר">
                                {removing === a.assignment_id ? "…" : "✕"}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                      {pendingPrimaries.map(c => (
                        <tr key={c.soldier_id} className="border-t dark:border-gray-600 bg-indigo-50 dark:bg-indigo-950/40">
                          <td className="p-2 text-indigo-700 dark:text-indigo-300">
                            {c.full_name}
                            <span className="mr-2 text-xs text-indigo-400">טרם נשמר</span>
                          </td>
                          <td className="p-2 text-indigo-500 dark:text-indigo-300">ראשי</td>
                          <td className="p-2 text-indigo-400 dark:text-indigo-500">
                            {pendingCoverageByPrimary[c.soldier_id] ?? "—"}
                          </td>
                          <td className="p-2 text-center">
                            <button type="button" onClick={() => togglePrimary(c.soldier_id)}
                              className="text-indigo-400 hover:text-indigo-600 text-sm leading-none" title="בטל בחירה">
                              ✕
                            </button>
                          </td>
                        </tr>
                      ))}
                      {currentReserves.map(a => {
                        const coveredNames = a.primary_assignment_ids
                          .map(id => assigneeNameById[id])
                          .filter(Boolean)
                          .join(", ") || "—";
                        return (
                          <tr key={a.assignment_id} className="border-t dark:border-gray-600 bg-gray-50/50 dark:bg-gray-700/30">
                            <td className="p-2 text-gray-600 dark:text-gray-400">{a.soldier_name}</td>
                            <td className="p-2 text-gray-400">רזרבה</td>
                            <td className="p-2 text-gray-400 dark:text-gray-500 max-w-[140px] truncate" title={coveredNames}>{coveredNames}</td>
                            <td className="p-2 text-center">
                              <button type="button" onClick={() => handleRemove(a.assignment_id)}
                                disabled={removing === a.assignment_id}
                                className="text-red-500 hover:text-red-700 disabled:opacity-40 text-sm leading-none" title="הסר">
                                {removing === a.assignment_id ? "…" : "✕"}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                      {pendingReserves.map(c => {
                        const coveringPrimaryNames = reserveCandidateCoverage[c.soldier_id]?.join(", ") || "—";
                        return (
                        <tr key={c.soldier_id} className="border-t dark:border-gray-600 bg-indigo-50/50 dark:bg-indigo-950/20">
                          <td className="p-2 text-indigo-600 dark:text-indigo-300">
                            {c.full_name}
                            <span className="mr-2 text-xs text-indigo-300">טרם נשמר</span>
                          </td>
                          <td className="p-2 text-indigo-400">רזרבה</td>
                          <td className="p-2 text-indigo-400 dark:text-indigo-500">{coveringPrimaryNames}</td>
                          <td className="p-2 text-center">
                            <button type="button" onClick={() => toggleReserve(c.soldier_id)}
                              className="text-indigo-400 hover:text-indigo-600 text-sm leading-none" title="בטל בחירה">
                              ✕
                            </button>
                          </td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Add primaries */}
            <div className="border dark:border-gray-600 rounded">
              <button
                type="button"
                onClick={() => setPrimaryPanelOpen(v => !v)}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700/50 rounded-t"
              >
                <span>{primaryPanelOpen ? "▾" : "▸"}</span>
                <span>הוסף ראשיים</span>
                <span className="text-xs font-normal text-gray-500 dark:text-gray-400">
                  {primarySlotsLeft > 0 ? `נותרו ${primarySlotsLeft} מקומות` : "מלאה"}
                </span>
                {primarySelected.size > 0 && (
                  <span className="mr-auto text-xs text-indigo-600 dark:text-indigo-300">{primarySelected.size} נבחרו</span>
                )}
              </button>
              {primaryPanelOpen && (
                <div className="border-t dark:border-gray-600 p-2 space-y-2">
                  <div className="flex gap-2 text-xs justify-end">
                    <button type="button" onClick={autoSelectPrimary}
                      disabled={primarySlotsLeft === 0 || unblockedCandidates.length === 0}
                      className="text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-40">
                      בחר אוטומטית
                    </button>
                    <button type="button" onClick={() => setPrimarySelected(new Set())}
                      className="text-blue-600 dark:text-blue-400 hover:underline">
                      בטל
                    </button>
                  </div>
                  <CandidateTable
                    unblocked={unblockedCandidates}
                    blocked={blockedCandidates}
                    selected={primarySelected}
                    onToggle={togglePrimary}
                  />
                </div>
              )}
            </div>

            {/* Add reserves */}
            <div className="border dark:border-gray-600 rounded">
              <button
                type="button"
                onClick={() => setReservePanelOpen(v => !v)}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700/50 rounded-t"
              >
                <span>{reservePanelOpen ? "▾" : "▸"}</span>
                <span>הוסף רזרבות</span>
                {totalReserveSlots > 0 && (
                  <span className="text-xs font-normal text-gray-500 dark:text-gray-400">
                    {reserveSlotsLeft > 0 ? `נותרו ${reserveSlotsLeft} מקומות` : "מלאה"}
                  </span>
                )}
                {reserveSelected.size > 0 && (
                  <span className="mr-auto text-xs text-indigo-600 dark:text-indigo-300">{reserveSelected.size} נבחרו</span>
                )}
              </button>
              {reservePanelOpen && (
                <div className="border-t dark:border-gray-600 p-2 space-y-2">
                  <div className="flex gap-2 text-xs justify-end">
                    <button type="button" onClick={autoSelectReserves}
                      disabled={reserveCandidates.unblocked.length === 0}
                      className="text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-40">
                      בחר אוטומטית
                    </button>
                    <button type="button" onClick={() => setReserveSelected(new Set())}
                      className="text-blue-600 dark:text-blue-400 hover:underline">
                      בטל
                    </button>
                  </div>
                  <ReserveCandidateTable
                    unblocked={reserveCandidates.unblocked}
                    blocked={reserveCandidates.blocked}
                    selected={reserveSelected}
                    onToggle={toggleReserve}
                    showDist={allPrimariesForMatching.length > 0}
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {error && <p className="text-red-500 text-xs mt-2">{error}</p>}

        <div className="flex justify-end gap-2 mt-4 pt-3 border-t dark:border-gray-600 flex-wrap">
          <button type="button" onClick={onClose} className="px-3 py-1.5 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">
            {t("shifts.dismiss")}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave || saving}
            className="px-4 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "שומר..." : `שמור${totalSelected > 0 ? ` (${totalSelected})` : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}

interface CandidateTableProps {
  unblocked: ShiftCandidate[];
  blocked: ShiftCandidate[];
  selected: Set<string>;
  onToggle: (id: string) => void;
}

function CandidateTable({ unblocked, blocked, selected, onToggle }: CandidateTableProps) {
  const [blockedOpen, setBlockedOpen] = useState(false);
  return (
    <div className="border dark:border-gray-600 rounded overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-gray-50 dark:bg-gray-700 sticky top-0">
          <tr>
            <th className="p-2 w-8"></th>
            <th className="text-right p-2 font-medium">שם</th>
            <th className="text-right p-2 font-medium">מ&quot;א</th>
            <th className="text-right p-2 font-medium">מאמץ</th>
            <th className="p-2"></th>
          </tr>
        </thead>
        <tbody>
          {unblocked.length === 0 && blocked.length === 0 && (
            <tr><td colSpan={5} className="p-2 text-center text-gray-400 italic">אין מועמדים זמינים</td></tr>
          )}
          {unblocked.map(c => (
            <tr key={c.soldier_id}
              className="border-t dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
              onClick={() => onToggle(c.soldier_id)}>
              <td className="p-2"><input type="checkbox" checked={selected.has(c.soldier_id)} onChange={() => onToggle(c.soldier_id)} onClick={e => e.stopPropagation()} /></td>
              <td className="p-2">{c.full_name}</td>
              <td className="p-2 text-gray-500 dark:text-gray-400" dir="ltr">{c.personal_number}</td>
              <td className="p-2 font-mono">{c.effort.toFixed(3)}</td>
              <td className="p-2"></td>
            </tr>
          ))}
          {blocked.length > 0 && (
            <tr className="border-t dark:border-gray-600">
              <td colSpan={5} className="px-2 py-1 bg-gray-50 dark:bg-gray-700/50">
                <button type="button" onClick={() => setBlockedOpen(v => !v)}
                  className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 flex items-center gap-1">
                  <span>{blockedOpen ? "▾" : "▸"}</span>
                  <span>חסומים ({blocked.length})</span>
                </button>
              </td>
            </tr>
          )}
          {blockedOpen && blocked.map(c => (
            <tr key={c.soldier_id} className="border-t dark:border-gray-600 opacity-40">
              <td className="p-2"><input type="checkbox" disabled /></td>
              <td className="p-2">{c.full_name}</td>
              <td className="p-2 text-gray-500 dark:text-gray-400" dir="ltr">{c.personal_number}</td>
              <td className="p-2 font-mono">{c.effort.toFixed(3)}</td>
              <td className="p-2 text-gray-400 whitespace-nowrap">{c.blocked_reason ? BLOCKED_REASON_LABEL[c.blocked_reason] : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReserveCandidateTable({ unblocked, blocked, selected, onToggle, showDist }: {
  unblocked: ReserveCandidate[];
  blocked: ShiftCandidate[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  showDist: boolean;
}) {
  const [blockedOpen, setBlockedOpen] = useState(false);
  const cols = showDist ? 6 : 5;
  return (
    <div className="border dark:border-gray-600 rounded overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-gray-50 dark:bg-gray-700 sticky top-0">
          <tr>
            <th className="p-2 w-8"></th>
            <th className="text-right p-2 font-medium">שם</th>
            <th className="text-right p-2 font-medium">מ&quot;א</th>
            <th className="text-right p-2 font-medium">מאמץ</th>
            {showDist && <th className="text-right p-2 font-medium">מחפה על</th>}
            <th className="p-2"></th>
          </tr>
        </thead>
        <tbody>
          {unblocked.length === 0 && blocked.length === 0 && (
            <tr><td colSpan={cols} className="p-2 text-center text-gray-400 italic">אין מועמדים זמינים</td></tr>
          )}
          {unblocked.map(c => (
            <tr key={c.soldier_id}
              className="border-t dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
              onClick={() => onToggle(c.soldier_id)}>
              <td className="p-2"><input type="checkbox" checked={selected.has(c.soldier_id)} onChange={() => onToggle(c.soldier_id)} onClick={e => e.stopPropagation()} /></td>
              <td className="p-2">{c.full_name}</td>
              <td className="p-2 text-gray-500 dark:text-gray-400" dir="ltr">{c.personal_number}</td>
              <td className="p-2 font-mono">{c.effort.toFixed(3)}</td>
              {showDist && <td className="p-2 text-gray-600 dark:text-gray-300 max-w-[160px]">{c.coveringNames.join(", ") || "–"}</td>}
              <td className="p-2"></td>
            </tr>
          ))}
          {blocked.length > 0 && (
            <tr className="border-t dark:border-gray-600">
              <td colSpan={cols} className="px-2 py-1 bg-gray-50 dark:bg-gray-700/50">
                <button type="button" onClick={() => setBlockedOpen(v => !v)}
                  className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 flex items-center gap-1">
                  <span>{blockedOpen ? "▾" : "▸"}</span>
                  <span>חסומים ({blocked.length})</span>
                </button>
              </td>
            </tr>
          )}
          {blockedOpen && blocked.map(c => (
            <tr key={c.soldier_id} className="border-t dark:border-gray-600 opacity-40">
              <td className="p-2"><input type="checkbox" disabled /></td>
              <td className="p-2">{c.full_name}</td>
              <td className="p-2 text-gray-500 dark:text-gray-400" dir="ltr">{c.personal_number}</td>
              <td className="p-2 font-mono">{c.effort.toFixed(3)}</td>
              {showDist && <td className="p-2"></td>}
              <td className="p-2 text-gray-400 whitespace-nowrap">{c.blocked_reason ? BLOCKED_REASON_LABEL[c.blocked_reason] : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
