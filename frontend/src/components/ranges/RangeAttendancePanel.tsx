import { useState } from "react";
import { markRangeAttendance, RangeAssignment, RangeAttendanceStatus } from "../../api/ranges";

interface Props {
  eventId: string;
  assignments: RangeAssignment[];
  onMarked: () => void;
  soldierName?: (id: string) => string;
}

export default function RangeAttendancePanel({ eventId, assignments, onMarked, soldierName }: Props) {
  const [pendingStatus, setPendingStatus] = useState<Record<string, RangeAttendanceStatus>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  function setStatus(assignmentId: string, status: RangeAttendanceStatus) {
    setPendingStatus((prev) => ({ ...prev, [assignmentId]: status }));
  }

  async function submit(assignmentId: string) {
    const status = pendingStatus[assignmentId];
    if (!status || submitting[assignmentId]) return;
    setSubmitting((prev) => ({ ...prev, [assignmentId]: true }));
    setErrors((prev) => ({ ...prev, [assignmentId]: "" }));
    try {
      await markRangeAttendance(eventId, assignmentId, status, notes[assignmentId]);
      onMarked();
    } catch {
      setErrors((prev) => ({ ...prev, [assignmentId]: "שגיאה בשמירת הנוכחות, נסה שוב" }));
    } finally {
      setSubmitting((prev) => ({ ...prev, [assignmentId]: false }));
    }
  }

  return (
    <div className="space-y-2" dir="rtl">
      <h3 className="font-medium text-sm text-gray-500 dark:text-gray-400">נוכחות</h3>
      {assignments.map((a) => {
        const status = pendingStatus[a.id];
        const canSubmit = status === "present" || (status === "no_show" && !!notes[a.id]);
        return (
          <div
            key={a.id}
            className="flex flex-wrap items-center gap-2 p-2 border rounded dark:border-gray-700 text-sm"
          >
            <span className="min-w-24 font-medium">{soldierName ? soldierName(a.soldier_id) : a.soldier_id}</span>
            <button
              data-testid={`present-${a.id}`}
              onClick={() => setStatus(a.id, "present")}
              className={`px-2 py-1 rounded text-xs font-medium ${
                status === "present"
                  ? "bg-green-600 text-white"
                  : "bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-800"
              }`}
            >
              נכח
            </button>
            <button
              data-testid={`no-show-${a.id}`}
              onClick={() => setStatus(a.id, "no_show")}
              className={`px-2 py-1 rounded text-xs font-medium ${
                status === "no_show"
                  ? "bg-red-600 text-white"
                  : "bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800"
              }`}
            >
              לא נכח
            </button>
            {status === "no_show" && (
              <input
                data-testid={`note-${a.id}`}
                value={notes[a.id] ?? ""}
                onChange={(e) => setNotes((prev) => ({ ...prev, [a.id]: e.target.value }))}
                placeholder="סיבה (חובה)"
                className="border rounded p-1 text-sm flex-1 min-w-40 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              />
            )}
            <button
              data-testid={`submit-${a.id}`}
              disabled={!canSubmit || submitting[a.id]}
              onClick={() => submit(a.id)}
              className="bg-indigo-600 text-white px-3 py-1 rounded text-xs font-medium hover:bg-indigo-700 disabled:opacity-40"
            >
              אשר
            </button>
            {errors[a.id] && (
              <span data-testid={`error-${a.id}`} className="text-xs text-red-600 dark:text-red-400 w-full">
                {errors[a.id]}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
