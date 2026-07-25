import { useEffect, useState } from "react";
import { DutyShift, TwoLevelSplitEntry, getTwoLevelSplitPreview, setShiftQuotas } from "../api/shifts";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  selectedShifts: DutyShift[];
  onApplied: () => void;
  onClose: () => void;
  dtName: (id: string) => string;
  locName: (id: string) => string;
}

interface ShiftPreview {
  shift: DutyShift;
  entries: TwoLevelSplitEntry[] | null;
  error: string | null;
}

export default function SplitInUnitModal({ selectedShifts, onApplied, onClose, dtName, locName }: Props) {
  useModalBackClose(onClose);
  const [previews, setPreviews] = useState<ShiftPreview[]>([]);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all(
      selectedShifts.map(async (shift) => {
        try {
          const entries = await getTwoLevelSplitPreview(shift.id);
          return { shift, entries, error: null } satisfies ShiftPreview;
        } catch {
          return { shift, entries: null, error: "לא ניתן לחשב פיצול (אין יחידה אחראית?)" } satisfies ShiftPreview;
        }
      })
    ).then((results) => { if (!cancelled) { setPreviews(results); setLoading(false); } });
    return () => { cancelled = true; };
  }, [selectedShifts]);

  async function handleApply() {
    setApplying(true);
    setApplyError(null);
    try {
      const applicable = previews.filter((p): p is ShiftPreview & { entries: TwoLevelSplitEntry[] } => !!p.entries);
      const results = await Promise.allSettled(
        applicable.map((p) =>
          setShiftQuotas(
            p.shift.id,
            p.entries.filter((e) => e.count > 0).map((e) => ({ hierarchy_node_id: e.hierarchy_node_id, count: e.count }))
          )
        )
      );
      const succeeded = results.filter((r) => r.status === "fulfilled").length;
      const failed = results.length - succeeded;
      if (failed > 0 && succeeded > 0) {
        setApplyError(`${succeeded} מתוך ${results.length} הצליחו`);
      } else if (failed > 0) {
        setApplyError("שגיאה בהחלת הפיצול");
      }
      if (succeeded > 0) {
        onApplied();
      }
    } catch {
      setApplyError("שגיאה בהחלת הפיצול");
    } finally {
      setApplying(false);
    }
  }

  const anyApplicable = previews.some((p) => p.entries && p.entries.length > 0);

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">פיצול מכסות ביחידה</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>

        {loading && <p className="text-sm text-gray-500">מחשב פיצול...</p>}

        {!loading && (
          <div className="space-y-4">
            {previews.map((p) => (
              <div key={p.shift.id} className="border dark:border-gray-600 rounded p-2">
                <p className="text-sm font-medium mb-1">
                  {p.shift.start_date} — {dtName(p.shift.duty_type_id)}, {locName(p.shift.duty_location_id)} — {p.shift.required_count} נדרשים
                </p>
                {p.error && <p className="text-xs text-red-500">{p.error}</p>}
                {p.entries && (
                  <table className="w-full text-xs">
                    <tbody>
                      {p.entries.map((e) => (
                        <tr key={e.hierarchy_node_id}>
                          <td className="p-1">{e.node_name}</td>
                          <td className="p-1 text-left">{e.count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
          </div>
        )}

        {applyError && <p className="text-red-500 text-xs mt-2">{applyError}</p>}

        <div className="flex justify-end gap-2 mt-4">
          <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">ביטול</button>
          <button
            type="button"
            disabled={loading || applying || !anyApplicable}
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
