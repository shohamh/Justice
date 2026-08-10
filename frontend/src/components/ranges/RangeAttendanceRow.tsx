import { useState } from "react";
import { markRangeAttendance, RangeAssignment, RangeAttendanceStatus } from "../../api/ranges";

interface Props {
  eventId: string;
  assignment: RangeAssignment;
  onMarked: () => void;
}

export function RangeAttendanceRow({ eventId, assignment, onMarked }: Props) {
  const [status, setStatus] = useState<RangeAttendanceStatus | null>(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const isCorrection = assignment.attendance_status !== "pending" && status !== null && status !== assignment.attendance_status;
  const noteRequired = status === "no_show" || isCorrection;
  const canSubmit = !!status && (!noteRequired || !!note);

  async function submit() {
    if (!status || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await markRangeAttendance(eventId, assignment.id, status, note || undefined);
      onMarked();
    } catch {
      setError("שגיאה בשמירת הנוכחות, נסה שוב");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <span className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        data-testid={`present-${assignment.id}`}
        onClick={() => setStatus("present")}
        className={`px-2 py-1 rounded text-xs font-medium ${
          status === "present"
            ? "bg-green-600 text-white"
            : "bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-800"
        }`}
      >
        נכח
      </button>
      <button
        type="button"
        data-testid={`no-show-${assignment.id}`}
        onClick={() => setStatus("no_show")}
        className={`px-2 py-1 rounded text-xs font-medium ${
          status === "no_show"
            ? "bg-red-600 text-white"
            : "bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800"
        }`}
      >
        לא נכח
      </button>
      {noteRequired && (
        <input
          data-testid={`note-${assignment.id}`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="סיבה (חובה)"
          className="border rounded p-1 text-sm flex-1 min-w-40 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
        />
      )}
      <button
        type="button"
        data-testid={`submit-${assignment.id}`}
        disabled={!canSubmit || submitting}
        onClick={submit}
        className="bg-indigo-600 text-white px-3 py-1 rounded text-xs font-medium hover:bg-indigo-700 disabled:opacity-40"
      >
        אשר
      </button>
      {error && (
        <span data-testid={`error-${assignment.id}`} className="text-xs text-red-600 dark:text-red-400 w-full">
          {error}
        </span>
      )}
    </span>
  );
}

export default RangeAttendanceRow;
