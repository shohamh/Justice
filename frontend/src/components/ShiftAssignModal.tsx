import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyShift, assignBatch } from "../api/shifts";
import { DutyType } from "../api/dutyConfig";
import { ShiftCandidate, getShiftCandidates } from "../api/assignments";
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

const WEAPON_WARNING_LABEL = "ללא הכשרת נשק בתוקף";

function hierarchyDistance(pathA: string[], pathB: string[]): number {
  let common = 0;
  while (common < pathA.length && common < pathB.length && pathA[common] === pathB[common]) {
    common++;
  }
  return (pathA.length - common) + (pathB.length - common);
}

type ReserveCandidate = ShiftCandidate & { dist: number; coveringNames: string[] };

export default function ShiftAssignModal({ shift, dutyTypes, onSaved, onClose }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const [candidates, setCandidates] = useState<ShiftCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [primarySelected, setPrimarySelected] = useState<Set<string>>(new Set());
  const [reserveSelected, setReserveSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dutyTypeName = dutyTypes.find(d => d.id === shift.duty_type_id)?.name ?? "";
  const primarySlotsLeft = Math.max(0, shift.required_count - shift.assigned_count);
  const totalReserveSlots = shift.reserve_count_override ?? shift.calculated_reserve_count ?? 0;
  const reserveSlotsLeft = Math.max(0, totalReserveSlots - shift.reserve_assigned_count);

  useEffect(() => {
    setLoading(true);
    getShiftCandidates(shift.id)
      .then(setCandidates)
      .catch(() => setError("שגיאה בטעינת מועמדים"))
      .finally(() => setLoading(false));
  }, [shift.id]);

  const unblockedCandidates = useMemo(() => candidates.filter(c => !c.blocked), [candidates]);
  const blockedCandidates = useMemo(() => candidates.filter(c => c.blocked), [candidates]);

  const selectedPrimaryCandidates = useMemo(
    () => unblockedCandidates.filter(c => primarySelected.has(c.soldier_id)),
    [unblockedCandidates, primarySelected]
  );

  const reserveCandidates = useMemo(() => {
    const available = candidates.filter(c => !primarySelected.has(c.soldier_id));
    const unblocked = available.filter(c => !c.blocked);
    const blocked = available.filter(c => c.blocked);

    const withDist: ReserveCandidate[] = unblocked.map(c => {
      if (selectedPrimaryCandidates.length === 0) {
        return { ...c, dist: Infinity, coveringNames: [] };
      }
      let minDist = Infinity;
      const covering: string[] = [];
      for (const p of selectedPrimaryCandidates) {
        const d = hierarchyDistance(c.hierarchy_path_ids, p.hierarchy_path_ids);
        if (d < minDist) {
          minDist = d;
          covering.length = 0;
          covering.push(p.full_name);
        } else if (d === minDist) {
          covering.push(p.full_name);
        }
      }
      return { ...c, dist: minDist, coveringNames: covering };
    });

    withDist.sort((a, b) => {
      if (a.dist !== b.dist) return a.dist - b.dist;
      return a.effort - b.effort;
    });

    return { unblocked: withDist, blocked };
  }, [candidates, primarySelected, selectedPrimaryCandidates]);

  function togglePrimary(id: string) {
    setPrimarySelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
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
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function selectAllPrimary() {
    const top = unblockedCandidates.slice(0, primarySlotsLeft).map(c => c.soldier_id);
    setPrimarySelected(new Set(top));
    setReserveSelected(prev => {
      const next = new Set(prev);
      top.forEach(id => next.delete(id));
      return next;
    });
  }

  function autoSelectReserves() {
    const top = reserveCandidates.unblocked
      .slice(0, reserveSlotsLeft)
      .map(c => c.soldier_id);
    setReserveSelected(new Set(top));
  }

  async function handleAssign() {
    if (primarySelected.size === 0 && reserveSelected.size === 0) return;
    const selectedIds = new Set([...primarySelected, ...reserveSelected]);
    const hasWeaponWarning = candidates.some(c => selectedIds.has(c.soldier_id) && c.weapon_warning);
    if (hasWeaponWarning) {
      const confirmed = window.confirm(
        "חלק מהחיילים שנבחרו אינם כשירים מבחינת הכשרת נשק לתורנות זו. לשבץ בכל זאת?"
      );
      if (!confirmed) return;
    }
    setSaving(true);
    setError(null);
    try {
      await assignBatch(shift.id, {
        primaries: [...primarySelected],
        reserves: [...reserveSelected],
      });
      onSaved();
    } catch (e: unknown) {
      setError(translateApiError(e, t, "שגיאה בשיבוץ"));
      setSaving(false);
    }
  }

  const totalSelected = primarySelected.size + reserveSelected.size;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-2xl w-full mx-4 flex flex-col max-h-[90vh]" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-start mb-3">
          <div>
            <h3 className="text-lg font-semibold">{t("shifts.assign_modal_title")}</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {dutyTypeName} · {shift.start_date} עד {lastDutyDay(shift.end_date)}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-lg">✕</button>
        </div>

        {loading && <p className="text-sm text-gray-500 py-6 text-center">טוען...</p>}
        {!loading && candidates.length === 0 && (
          <p className="text-sm text-gray-500 py-6 text-center">אין חיילים זכאים</p>
        )}

        {!loading && candidates.length > 0 && (
          <div className="overflow-y-auto flex-1 space-y-4">
            {/* Primary section */}
            <div>
              <div className="flex items-center gap-3 mb-1 flex-wrap">
                <span className="text-sm font-medium">ראשיים</span>
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {primarySlotsLeft > 0 ? `נותרו ${primarySlotsLeft} מקומות` : "מלאה"}
                </span>
                <div className="mr-auto flex gap-2 text-xs">
                  <button type="button" onClick={selectAllPrimary} disabled={primarySlotsLeft === 0}
                    className="text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-40">
                    בחר הכל
                  </button>
                  <button type="button" onClick={() => setPrimarySelected(new Set())}
                    className="text-blue-600 dark:text-blue-400 hover:underline">
                    בטל
                  </button>
                  <span className="text-gray-500 dark:text-gray-400">{primarySelected.size} נבחרו</span>
                </div>
              </div>
              <PrimaryTable
                unblocked={unblockedCandidates}
                blocked={blockedCandidates}
                selected={primarySelected}
                onToggle={togglePrimary}
              />
            </div>

            {/* Reserve section */}
            {totalReserveSlots > 0 && (
              <div>
                <div className="flex items-center gap-3 mb-1 flex-wrap">
                  <span className="text-sm font-medium">רזרביים</span>
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {reserveSlotsLeft > 0 ? `נותרו ${reserveSlotsLeft} מקומות` : "מלאה"}
                  </span>
                  <div className="mr-auto flex gap-2 text-xs">
                    <button
                      type="button"
                      onClick={autoSelectReserves}
                      disabled={primarySelected.size === 0 || reserveSlotsLeft === 0}
                      className="text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-40"
                    >
                      בחר אוטומטית
                    </button>
                    <button type="button" onClick={() => setReserveSelected(new Set())}
                      className="text-blue-600 dark:text-blue-400 hover:underline">
                      בטל
                    </button>
                    <span className="text-gray-500 dark:text-gray-400">{reserveSelected.size} נבחרו</span>
                  </div>
                </div>
                <ReserveTable
                  unblocked={reserveCandidates.unblocked}
                  blocked={reserveCandidates.blocked}
                  selected={reserveSelected}
                  onToggle={toggleReserve}
                  showDist={primarySelected.size > 0}
                />
              </div>
            )}
          </div>
        )}

        {error && <p className="text-red-500 text-xs mt-2">{error}</p>}

        <div className="flex justify-end gap-2 mt-4 pt-3 border-t dark:border-gray-600 flex-wrap">
          <button type="button" onClick={onClose} className="px-3 py-1.5 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">
            {t("shifts.dismiss")}
          </button>
          <button
            type="button"
            onClick={handleAssign}
            disabled={totalSelected === 0 || saving}
            className="px-4 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "משבץ..." : `שבץ${totalSelected > 0 ? ` (${totalSelected})` : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// — Primary table —
interface PrimaryTableProps {
  unblocked: ShiftCandidate[];
  blocked: ShiftCandidate[];
  selected: Set<string>;
  onToggle: (id: string) => void;
}

function PrimaryTable({ unblocked, blocked, selected, onToggle }: PrimaryTableProps) {
  const [blockedOpen, setBlockedOpen] = useState(true);
  const cols = 5;
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
          {unblocked.map(c => (
            <tr key={c.soldier_id}
              className="border-t dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
              onClick={() => onToggle(c.soldier_id)}>
              <td className="p-2"><input type="checkbox" checked={selected.has(c.soldier_id)} onChange={() => onToggle(c.soldier_id)} onClick={e => e.stopPropagation()} /></td>
              <td className="p-2">
                {c.full_name}
                {c.weapon_warning && (
                  <span title={WEAPON_WARNING_LABEL} className="mr-1 text-amber-500 dark:text-amber-400">⚠️</span>
                )}
              </td>
              <td className="p-2 text-gray-500 dark:text-gray-400" dir="ltr">{c.personal_number}</td>
              <td className="p-2 font-mono">{c.effort.toFixed(3)}</td>
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
              <td className="p-2 text-gray-400 whitespace-nowrap">{c.blocked_reason === "ineligible" ? "אי־כשיר לסוג תורנות זה" : c.blocked_reason ? BLOCKED_REASON_LABEL[c.blocked_reason] : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// — Reserve table —
interface ReserveTableProps {
  unblocked: ReserveCandidate[];
  blocked: ShiftCandidate[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  showDist: boolean;
}

function ReserveTable({ unblocked, blocked, selected, onToggle, showDist }: ReserveTableProps) {
  const [blockedOpen, setBlockedOpen] = useState(true);
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
          {unblocked.map(c => (
            <tr key={c.soldier_id}
              className="border-t dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
              onClick={() => onToggle(c.soldier_id)}>
              <td className="p-2"><input type="checkbox" checked={selected.has(c.soldier_id)} onChange={() => onToggle(c.soldier_id)} onClick={e => e.stopPropagation()} /></td>
              <td className="p-2">
                {c.full_name}
                {c.weapon_warning && (
                  <span title={WEAPON_WARNING_LABEL} className="mr-1 text-amber-500 dark:text-amber-400">⚠️</span>
                )}
              </td>
              <td className="p-2 text-gray-500 dark:text-gray-400" dir="ltr">{c.personal_number}</td>
              <td className="p-2 font-mono">{c.effort.toFixed(3)}</td>
              {showDist && (
                <td className="p-2 text-gray-600 dark:text-gray-300 max-w-[160px]">
                  {c.coveringNames.length > 0 ? c.coveringNames.join(", ") : "–"}
                </td>
              )}
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
              <td className="p-2 text-gray-400 whitespace-nowrap">{c.blocked_reason === "ineligible" ? "אי־כשיר לסוג תורנות זה" : c.blocked_reason ? BLOCKED_REASON_LABEL[c.blocked_reason] : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
