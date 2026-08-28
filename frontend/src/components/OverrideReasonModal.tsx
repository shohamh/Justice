import { useState } from "react";

interface Props {
  open: boolean;
  count: number;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}

export default function OverrideReasonModal({ open, count, onCancel, onConfirm }: Props) {
  const [reason, setReason] = useState("");
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-[60]" onClick={onCancel}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <h4 className="text-sm font-semibold mb-2">
          {count === 1 ? "שיבוץ עם אילוץ אישי מאושר" : `שיבוץ ${count} חיילים עם אילוץ אישי מאושר`}
        </h4>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
          נדרש נימוק לעקיפת האילוץ. הנימוק יישלח לחייל/ים ולמפקדם.
        </p>
        <textarea
          className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          rows={3}
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="נימוק העקיפה..."
        />
        <div className="flex justify-end gap-2 mt-3">
          <button type="button" onClick={onCancel} className="px-3 py-1.5 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">
            ביטול
          </button>
          <button
            type="button"
            onClick={() => onConfirm(reason.trim())}
            disabled={!reason.trim()}
            className="px-4 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            אישור
          </button>
        </div>
      </div>
    </div>
  );
}
