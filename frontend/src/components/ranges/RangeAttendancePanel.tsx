import { useState } from "react";
import { markRangeAttendance, RangeAssignment, RangeAttendanceStatus } from "../../api/ranges";

interface Props {
  eventId: string;
  assignments: RangeAssignment[];
  onMarked: () => void;
}

export default function RangeAttendancePanel({ eventId, assignments, onMarked }: Props) {
  const [pendingStatus, setPendingStatus] = useState<Record<string, RangeAttendanceStatus>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});

  function setStatus(assignmentId: string, status: RangeAttendanceStatus) {
    setPendingStatus((prev) => ({ ...prev, [assignmentId]: status }));
  }

  async function submit(assignmentId: string) {
    const status = pendingStatus[assignmentId];
    if (!status) return;
    await markRangeAttendance(eventId, assignmentId, status, notes[assignmentId]);
    onMarked();
  }

  return (
    <div dir="rtl">
      {assignments.map((a) => {
        const status = pendingStatus[a.id];
        const canSubmit = status === "present" || (status === "no_show" && !!notes[a.id]);
        return (
          <div key={a.id}>
            <span>{a.soldier_id}</span>
            <button data-testid={`present-${a.id}`} onClick={() => setStatus(a.id, "present")}>
              נכח
            </button>
            <button data-testid={`no-show-${a.id}`} onClick={() => setStatus(a.id, "no_show")}>
              לא נכח
            </button>
            {status === "no_show" && (
              <input
                data-testid={`note-${a.id}`}
                value={notes[a.id] ?? ""}
                onChange={(e) => setNotes((prev) => ({ ...prev, [a.id]: e.target.value }))}
                placeholder="סיבה (חובה)"
              />
            )}
            <button data-testid={`submit-${a.id}`} disabled={!canSubmit} onClick={() => submit(a.id)}>
              אשר
            </button>
          </div>
        );
      })}
    </div>
  );
}
