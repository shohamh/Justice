import { useState } from "react";
import { useTranslation } from "react-i18next";
import { SwapRequest, submitCoverOffer } from "../api/swaps";
import { EffectiveDuty } from "../api/assignments";

interface Props {
  swap: SwapRequest;
  myDuties: EffectiveDuty[];
  dutyTypes: Record<string, string>;
  onClose: () => void;
  onDone: () => void;
}

export default function CoverOfferModal({ swap, myDuties, dutyTypes, onClose, onDone }: Props) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"free" | "trade">("free");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  function toggleDuty(id: string) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function handleSubmit() {
    setError(null);
    try {
      await submitCoverOffer(swap.id, mode === "trade" ? selectedIds : []);
      onDone();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold dark:text-gray-100">{t("swaps.cover")}</h3>
          <button onClick={onClose} className="text-gray-500">✕</button>
        </div>
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input type="radio" name="cover_mode" checked={mode === "free"} onChange={() => setMode("free")} />
            {t("swaps.cover_free")}
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input type="radio" name="cover_mode" checked={mode === "trade"} onChange={() => setMode("trade")} />
            {t("swaps.offer_trade")}
          </label>
          {mode === "trade" && (
            <div className="space-y-1 max-h-40 overflow-y-auto border rounded p-2 dark:border-gray-600">
              <p className="text-xs text-gray-500 mb-1">{t("swaps.select_duties_to_offer")}:</p>
              {myDuties
                .filter((d) => d.assignment_id !== swap.duty_assignment_id)
                .map((d) => (
                  <label key={d.assignment_id} className="flex items-center gap-2 text-xs cursor-pointer dark:text-gray-300">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(d.assignment_id)}
                      onChange={() => toggleDuty(d.assignment_id)}
                    />
                    <span>{dutyTypes[d.duty_type_id] ?? d.duty_type_id} — {d.start_date}</span>
                  </label>
                ))}
            </div>
          )}
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1 text-sm border rounded dark:border-gray-600 dark:text-gray-300"
            >
              {t("swaps.cancel")}
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={mode === "trade" && selectedIds.length === 0}
              className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
            >
              {t("swaps.submit_offer")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
