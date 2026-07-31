import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getRanges,
  getRangeEvent,
  addRangeAssignment,
  removeRangeAssignment,
  RangeEvent,
} from "../api/ranges";
import { queryKeys } from "../queryKeys";
import { useAuth } from "../auth/AuthContext";
import SoldierSearchAutocomplete from "../components/SoldierSearchAutocomplete";
import { SoldierDTO } from "../api/soldiers";

export default function RangesPage() {
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [showPicker, setShowPicker] = useState(false);
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const nodeId = user?.hierarchy_node_id ?? null;

  const { data: events } = useQuery({
    queryKey: queryKeys.ranges(),
    queryFn: () => getRanges(nodeId as string),
    enabled: !!nodeId,
  });
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

  async function handleAddSoldier(soldier: SoldierDTO | null) {
    if (!soldier || !selectedEventId) return;
    await addRangeAssignment(selectedEventId, soldier.id, false);
    queryClient.invalidateQueries({ queryKey: queryKeys.rangeEvent(selectedEventId) });
    setShowPicker(false);
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
          <button data-testid="add-soldier-button" onClick={() => setShowPicker(true)}>
            הוסף חייל
          </button>
          {showPicker && <SoldierSearchAutocomplete onSelect={handleAddSoldier} />}
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
