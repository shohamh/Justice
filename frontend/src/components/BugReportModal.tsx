import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { translateApiError } from "../utils/translateApiError";
import { submitBugReport } from "../api/bugReports";
import { useNavigationHistory } from "../hooks/useNavigationHistory";
import { useModalBackClose } from "../hooks/useModalBackClose";

type Severity = "low" | "medium" | "high";

const SEVERITIES: { value: Severity; label: string }[] = [
  { value: "low", label: "נמוכה" },
  { value: "medium", label: "בינונית" },
  { value: "high", label: "גבוהה" },
];

interface BugReportModalProps {
  screenshot: string | null;
  onClose: () => void;
}

export default function BugReportModal({ screenshot, onClose }: BugReportModalProps) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const location = useLocation();
  const navHistory = useNavigationHistory();
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<Severity>("medium");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [succeeded, setSucceeded] = useState(false);

  async function handleSubmit() {
    if (!description.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitBugReport({
        description: description.trim(),
        severity,
        screenshot: screenshot ? (screenshot.split(",")[1] ?? null) : null,
        route: location.pathname,
        nav_history: navHistory,
      });
      setSucceeded(true);
      setTimeout(onClose, 1200);
    } catch (err: unknown) {
      setError(translateApiError(err, t, "שגיאה בשליחת הדיווח"));
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-[110]"
      onClick={onClose}
      data-testid="bug-report-modal-overlay"
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-3">
          <h3 className="text-lg font-semibold">מצאתי באג</h3>
          <button
            onClick={onClose}
            className="p-1 -m-1 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            aria-label="סגור"
            data-testid="bug-report-modal-close"
          >
            <X size={20} />
          </button>
        </div>

        {succeeded ? (
          <p className="text-sm text-green-600" data-testid="bug-report-success">הדיווח נשלח בהצלחה, תודה!</p>
        ) : (
          <>
            <div className="mb-3">
              {screenshot ? (
                <img src={screenshot} alt="" className="w-full rounded border dark:border-gray-600" />
              ) : (
                <p className="text-xs text-gray-500">לא ניתן היה לצלם את המסך, אפשר להמשיך בלעדיו</p>
              )}
            </div>
            <textarea
              className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  if (!submitting && description.trim()) void handleSubmit();
                }
              }}
              maxLength={2000}
              placeholder="מה קרה?"
              data-testid="bug-report-description"
            />
            <div className="flex gap-2 mt-3" data-testid="bug-report-severity-picker">
              {SEVERITIES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  onClick={() => setSeverity(s.value)}
                  className={`flex-1 px-2 py-1 text-xs rounded border ${
                    severity === s.value
                      ? "bg-indigo-600 text-white border-indigo-600"
                      : "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300"
                  }`}
                  data-testid={`bug-report-severity-${s.value}`}
                >
                  {s.label}
                </button>
              ))}
            </div>
            {error && <p className="text-red-500 text-xs mt-2">{error}</p>}
            <div className="flex justify-end gap-2 mt-4">
              <button type="button" onClick={onClose} disabled={submitting} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50">
                ביטול
              </button>
              <button
                type="button"
                onClick={() => { void handleSubmit(); }}
                disabled={submitting || !description.trim()}
                className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
                data-testid="bug-report-submit"
              >
                {submitting ? "שולח..." : "שליחה"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
