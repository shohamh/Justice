import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyShift } from "../api/shifts";
import { DutyType } from "../api/dutyConfig";
import { ShiftCandidate, createAssignment, getShiftCandidates } from "../api/assignments";

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

export default function ShiftAssignModal({ shift, dutyTypes, onSaved, onClose }: Props) {
  const { t } = useTranslation();
  const [candidates, setCandidates] = useState<ShiftCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dutyTypeName = dutyTypes.find(d => d.id === shift.duty_type_id)?.name ?? "";

  useEffect(() => {
    setLoading(true);
    getShiftCandidates(shift.id)
      .then(setCandidates)
      .catch(() => setError("שגיאה בטעינת מועמדים"))
      .finally(() => setLoading(false));
  }, [shift.id]);

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function selectAll() {
    setSelected(new Set(candidates.filter(c => !c.blocked).map(c => c.soldier_id)));
  }

  async function handleAssign() {
    if (selected.size === 0) return;
    setSaving(true);
    setError(null);
    try {
      await Promise.all(
        [...selected].map(soldier_id =>
          createAssignment({
            soldier_id,
            duty_type_id: shift.duty_type_id,
            duty_location_id: shift.duty_location_id,
            start_date: shift.start_date,
            end_date: shift.end_date,
            duty_shift_id: shift.id,
          })
        )
      );
      onSaved();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה בשיבוץ");
      setSaving(false);
    }
  }

  const unblocked = candidates.filter(c => !c.blocked);
  const blocked = candidates.filter(c => c.blocked);
  const slotsLeft = shift.required_count - shift.assigned_count;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-lg w-full mx-4 flex flex-col max-h-[85vh]" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-start mb-1">
          <div>
            <h3 className="text-lg font-semibold">{t("shifts.assign_modal_title")}</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {dutyTypeName} · {shift.start_date} עד {shift.end_date} · {slotsLeft > 0 ? `נותרו ${slotsLeft} מקומות` : "מלאה"}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-lg">✕</button>
        </div>

        {loading && <p className="text-sm text-gray-500 py-6 text-center">טוען...</p>}

        {!loading && candidates.length === 0 && (
          <p className="text-sm text-gray-500 py-6 text-center">אין חיילים זכאים</p>
        )}

        {!loading && candidates.length > 0 && (
          <>
            <div className="flex items-center gap-3 mb-2 text-xs">
              <button type="button" onClick={selectAll} className="text-blue-600 dark:text-blue-400 hover:underline">בחר הכל</button>
              <button type="button" onClick={() => setSelected(new Set())} className="text-blue-600 dark:text-blue-400 hover:underline">בטל בחירה</button>
              <span className="text-gray-500 dark:text-gray-400 mr-auto">{selected.size} נבחרו</span>
            </div>

            <div className="overflow-y-auto flex-1 border dark:border-gray-600 rounded">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 dark:bg-gray-700 sticky top-0">
                  <tr>
                    <th className="p-2 w-8"></th>
                    <th className="text-right p-2 font-medium">שם</th>
                    <th className="text-right p-2 font-medium">מ"א</th>
                    <th className="text-right p-2 font-medium">מאמץ</th>
                    <th className="p-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {unblocked.map(c => (
                    <tr
                      key={c.soldier_id}
                      className="border-t dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
                      onClick={() => toggle(c.soldier_id)}
                    >
                      <td className="p-2">
                        <input type="checkbox" checked={selected.has(c.soldier_id)} onChange={() => toggle(c.soldier_id)} onClick={e => e.stopPropagation()} />
                      </td>
                      <td className="p-2">{c.full_name}</td>
                      <td className="p-2 text-gray-500 dark:text-gray-400" dir="ltr">{c.personal_number}</td>
                      <td className="p-2 font-mono">{c.effort.toFixed(3)}</td>
                      <td className="p-2"></td>
                    </tr>
                  ))}
                  {blocked.length > 0 && (
                    <tr className="border-t dark:border-gray-600">
                      <td colSpan={5} className="px-2 py-1 text-xs text-gray-400 dark:text-gray-500 bg-gray-50 dark:bg-gray-700/50">חסומים</td>
                    </tr>
                  )}
                  {blocked.map(c => (
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
          </>
        )}

        {error && <p className="text-red-500 text-xs mt-2">{error}</p>}

        <div className="flex justify-end gap-2 mt-4">
          <button type="button" onClick={onClose} className="px-3 py-1.5 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">
            {t("shifts.dismiss")}
          </button>
          <button
            type="button"
            onClick={handleAssign}
            disabled={selected.size === 0 || saving}
            className="px-4 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "משבץ..." : `שבץ ${selected.size > 0 ? `(${selected.size})` : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}
