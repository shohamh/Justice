import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getRanges,
  getRangeEvent,
  removeRangeAssignment,
  RangeEvent,
} from "../api/ranges";
import { queryKeys } from "../queryKeys";

export default function RangesPage() {
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: events } = useQuery({ queryKey: queryKeys.ranges(), queryFn: getRanges });
  const { data: selectedEvent } = useQuery({
    queryKey: queryKeys.rangeEvent(selectedEventId as string),
    queryFn: () => getRangeEvent(selectedEventId as string),
    enabled: selectedEventId !== null,
  });

  async function handleRemoveAssignment(assignmentId: string) {
    if (!selectedEventId) return;
    await removeRangeAssignment(selectedEventId, assignmentId);
    queryClient.invalidateQueries({ queryKey: queryKeys.rangeEvent(selectedEventId) });
  }

  return (
    <div dir="rtl">
      <h1>מטווחים</h1>
      <table>
        <thead>
          <tr>
            <th>תאריך</th>
            <th>סוג</th>
            <th>מיקום</th>
            <th>סטטוס</th>
          </tr>
        </thead>
        <tbody>
          {(events ?? []).map((event: RangeEvent) => (
            <tr key={event.id} onClick={() => setSelectedEventId(event.id)}>
              <td>{event.date}</td>
              <td>{event.range_type}</td>
              <td>{event.location}</td>
              <td>{event.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {selectedEvent && (
        <div>
          <h2>{selectedEvent.location}</h2>
          <ul>
            {selectedEvent.assignments.map((a) => (
              <li key={a.id}>
                {a.soldier_id} {a.is_reserve ? "(רזרבה)" : ""}
                <button onClick={() => handleRemoveAssignment(a.id)}>הסר</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
