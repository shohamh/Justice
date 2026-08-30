import { RangeAssignment, RangeAttendanceStatus } from "../../api/ranges";

interface Props {
  assignment: RangeAssignment;
  pendingStatus?: RangeAttendanceStatus;
  pendingNote?: string;
  onStatusChange: (status: RangeAttendanceStatus) => void;
  onNoteChange: (note: string) => void;
}

export function RangeAttendanceStatusPicker({ assignment, pendingStatus, pendingNote, onStatusChange, onNoteChange }: Props) {
  const status = pendingStatus ?? null;
  const isCorrection = assignment.attendance_status !== "pending" && status !== null && status !== assignment.attendance_status;
  const noteRequired = status === "no_show" || isCorrection;

  return (
    <span className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        data-testid={`present-${assignment.id}`}
        onClick={() => onStatusChange("present")}
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
        onClick={() => onStatusChange("no_show")}
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
          value={pendingNote ?? ""}
          onChange={(e) => onNoteChange(e.target.value)}
          placeholder="סיבה (חובה)"
          className="border rounded p-1 text-sm flex-1 min-w-40 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
        />
      )}
    </span>
  );
}

export default RangeAttendanceStatusPicker;
