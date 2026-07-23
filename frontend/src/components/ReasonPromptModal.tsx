import { useState } from "react";
import { useTranslation } from "react-i18next";
import { translateApiError } from "../utils/translateApiError";

interface Props {
  title: string;
  description?: string;
  confirmLabel?: string;
  onConfirm: (reason: string) => Promise<void>;
  onClose: () => void;
}

export default function ReasonPromptModal({ title, description, confirmLabel, onConfirm, onClose }: Props) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    if (!reason.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
    } catch (err: unknown) {
      setError(translateApiError(err, t, "שגיאה"));
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-3">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700" data-testid="reason-modal-close">✕</button>
        </div>
        {description && <p className="text-sm text-gray-600 dark:text-gray-300 mb-3">{description}</p>}
        <textarea
          className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="סיבה (חובה)"
          data-testid="reason-modal-textarea"
        />
        {error && <p className="text-red-500 text-xs mt-2">{error}</p>}
        <div className="flex justify-end gap-2 mt-4">
          <button type="button" onClick={onClose} disabled={submitting} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50">ביטול</button>
          <button
            type="button"
            onClick={() => { void handleConfirm(); }}
            disabled={submitting || !reason.trim()}
            className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
            data-testid="reason-modal-confirm"
          >
            {submitting ? "מבטל..." : (confirmLabel ?? "אישור")}
          </button>
        </div>
      </div>
    </div>
  );
}
