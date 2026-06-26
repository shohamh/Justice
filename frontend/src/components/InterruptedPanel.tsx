interface Props {
  reason: string;
  onRetry?: () => void;
  retrying?: boolean;
  retryError?: string | null;
}

const MESSAGES: Record<string, string> = {
  server_restarted: "שרת האפליקציה הופעל מחדש באמצע העיבוד, לפני שההרצה הושלמה.",
  timed_out: "ההרצה ארכה זמן רב מהמותר ובוטלה לפני שנמצא פתרון מלא.",
};

export default function InterruptedPanel({ reason, onRetry, retrying, retryError }: Props) {
  return (
    <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-4 space-y-2 text-sm" dir="rtl">
      <div className="flex items-center gap-2">
        <span className="text-amber-600 dark:text-amber-400 text-base">⚠️</span>
        <h3 className="font-semibold text-amber-700 dark:text-amber-300">ההרצה נקטעה</h3>
      </div>
      <p className="text-gray-700 dark:text-gray-300">
        {MESSAGES[reason] ?? "ההרצה נקטעה מסיבה לא צפויה."}
      </p>
      <p className="text-gray-600 dark:text-gray-400">
        זו לא בעיית שיבוץ — אין צורך לשנות הגדרות. ניתן פשוט להריץ שוב עם אותם נתונים.
      </p>
      {onRetry && (
        <div className="pt-1">
          <button
            onClick={onRetry}
            disabled={retrying}
            className="px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-medium"
          >
            {retrying ? "מריץ מחדש…" : "הרץ שוב"}
          </button>
          {retryError && (
            <p className="text-red-600 dark:text-red-400 text-xs mt-1">{retryError}</p>
          )}
        </div>
      )}
    </div>
  );
}
