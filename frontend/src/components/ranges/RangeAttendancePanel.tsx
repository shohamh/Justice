import { RangeAssignment } from "../../api/ranges";
import { RangeAttendanceRow } from "./RangeAttendanceRow";

interface Props {
  eventId: string;
  assignments: RangeAssignment[];
  onMarked: () => void;
  soldierName?: (id: string) => string;
}

export default function RangeAttendancePanel({ eventId, assignments, onMarked, soldierName }: Props) {
  return (
    <div className="space-y-2" dir="rtl">
      <h3 className="font-medium text-sm text-gray-500 dark:text-gray-400">נוכחות</h3>
      {assignments.map((a) => (
        <div
          key={a.id}
          className="flex flex-wrap items-center gap-2 p-2 border rounded dark:border-gray-700 text-sm"
        >
          <span className="min-w-24 font-medium">{soldierName ? soldierName(a.soldier_id) : a.soldier_id}</span>
          <RangeAttendanceRow eventId={eventId} assignment={a} onMarked={onMarked} />
        </div>
      ))}
    </div>
  );
}
