import { useState } from "react";
import { DutyShift, updateShift } from "../api/shifts";
import SubHierarchySelector from "./SubHierarchySelector";

interface Props {
  selectedShifts: DutyShift[];
  onApplied: () => void;
  onClose: () => void;
}

export default function SetResponsibleUnitsModal({ selectedShifts, onApplied, onClose }: Props) {
  const [nodeIds, setNodeIds] = useState<string[]>([]);
  const [stage, setStage] = useState<"pick" | "preview">("pick");
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleApply() {
    setApplying(true);
    setError(null);
    try {
      await Promise.all(
        selectedShifts.map((s) => updateShift(s.id, { eligible_node_ids: nodeIds }))
      );
      onApplied();
    } catch {
      setError("שגיאה בעדכון המשמרות");
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4 max-h-[90vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">קביעת יחידה אחראית</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>

        {stage === "pick" && (
          <>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-2">
              בחר יחידה אחת או יותר שתהיה אחראית על {selectedShifts.length} המשמרות שנבחרו.
            </p>
            <SubHierarchySelector value={nodeIds} onChange={setNodeIds} />
            <div className="flex justify-end gap-2 mt-4">
              <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">ביטול</button>
              <button
                type="button"
                disabled={nodeIds.length === 0}
                onClick={() => setStage("preview")}
                className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                המשך
              </button>
            </div>
          </>
        )}

        {stage === "preview" && (
          <>
            <p className="text-sm text-gray-700 dark:text-gray-200 mb-3">
              {selectedShifts.length} משמרות יעודכנו ליחידות אחראיות: {nodeIds.length} יחידות נבחרו.
            </p>
            {error && <p className="text-red-500 text-xs mb-2">{error}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setStage("pick")} disabled={applying} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50">חזרה</button>
              <button
                type="button"
                onClick={() => { void handleApply(); }}
                disabled={applying}
                className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {applying ? "מעדכן..." : "אישור"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
