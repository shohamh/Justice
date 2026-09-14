interface Props {
  open: boolean;
  saving: boolean;
  error: string | null;
  onSaveAndLeave: () => void;
  onDiscardAndLeave: () => void;
  onCancel: () => void;
}

export default function UnsavedChangesDialog({ open, saving, error, onSaveAndLeave, onDiscardAndLeave, onCancel }: Props) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-[100]" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        dir="rtl"
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-5 w-80"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="font-semibold text-base mb-2">יש שינויים שלא נשמרו</h3>
        <p className="text-sm text-gray-600 dark:text-gray-300 mb-3">
          אם תצא/י עכשיו, השינויים שביצעת יאבדו. מה לעשות?
        </p>
        {error && <p data-testid="unsaved-error" className="text-red-500 text-xs mb-3">{error}</p>}
        <div className="flex flex-col gap-2">
          <button
            type="button"
            data-testid="unsaved-save"
            disabled={saving}
            onClick={onSaveAndLeave}
            className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
          >
            {saving ? "שומר..." : "שמור וצא"}
          </button>
          <button
            type="button"
            data-testid="unsaved-discard"
            onClick={onDiscardAndLeave}
            className="border border-red-300 text-red-700 px-3 py-1.5 rounded text-sm"
          >
            צא בלי לשמור
          </button>
          <button
            type="button"
            data-testid="unsaved-cancel"
            onClick={onCancel}
            className="text-sm text-gray-500 dark:text-gray-400 hover:underline"
          >
            ביטול
          </button>
        </div>
      </div>
    </div>
  );
}
