import { useEffect, useState } from "react";
import { DutyShift, ResponsibilityAssignment, getAutoAssignResponsibilityPreview, updateShift } from "../api/shifts";

interface Props {
  selectedShifts: DutyShift[];
  onApplied: () => void;
  onClose: () => void;
}

export default function AutoAssignResponsibilityModal({ selectedShifts, onApplied, onClose }: Props) {
  const [assignments, setAssignments] = useState<ResponsibilityAssignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAutoAssignResponsibilityPreview(selectedShifts.map((s) => s.id))
      .then((result) => { if (!cancelled) { setAssignments(result); setLoading(false); } })
      .catch(() => { if (!cancelled) { setError("שגיאה בחישוב שיבוץ אחריות"); setLoading(false); } });
    return () => { cancelled = true; };
  }, [selectedShifts]);

  const shiftById = new Map(selectedShifts.map((s) => [s.id, s]));

  async function handleApply() {
    setApplying(true);
    setError(null);
    try {
      await Promise.all(
        assignments.map((a) => updateShift(a.shift_id, { eligible_node_ids: [a.hierarchy_node_id] }))
      );
      onApplied();
    } catch {
      setError("שגיאה בהחלת השיבוץ");
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-lg w-full mx-4 max-h-[90vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">שיבוץ אוטומטי של אחריות יחידה</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>

        {loading && <p className="text-sm text-gray-500">מחשב שיבוץ...</p>}

        {!loading && (
          <table className="w-full text-sm mb-3">
            <thead>
              <tr>
                <th className="text-right p-1 font-medium">משמרת</th>
                <th className="text-right p-1 font-medium">יחידה אחראית מוצעת</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((a) => (
                <tr key={a.shift_id} className="border-t dark:border-gray-600">
                  <td className="p-1">{shiftById.get(a.shift_id)?.start_date ?? a.shift_id.slice(0, 8)}</td>
                  <td className="p-1">{a.node_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {!loading && assignments.length < selectedShifts.length && (
          <p className="text-xs text-gray-500 mb-2">
            {selectedShifts.length - assignments.length} משמרות דולגו (ללא יחידות זכאיות מוגדרות).
          </p>
        )}

        {error && <p className="text-red-500 text-xs mb-2">{error}</p>}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">ביטול</button>
          <button
            type="button"
            disabled={loading || applying || assignments.length === 0}
            onClick={() => { void handleApply(); }}
            className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {applying ? "מעדכן..." : "אישור"}
          </button>
        </div>
      </div>
    </div>
  );
}
