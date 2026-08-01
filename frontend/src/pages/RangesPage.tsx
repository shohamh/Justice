import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getRanges,
  getRangeEvent,
  addRangeAssignment,
  removeRangeAssignment,
  createRangeEvent,
  RangeEvent,
  RangeType,
} from "../api/ranges";
import { queryKeys } from "../queryKeys";
import { useAuth } from "../auth/AuthContext";
import { canPlan } from "../auth/permissions";
import Layout from "../components/Layout";
import SoldierLink from "../components/SoldierLink";
import SoldierSearchAutocomplete from "../components/SoldierSearchAutocomplete";
import RangeAttendancePanel from "../components/ranges/RangeAttendancePanel";
import { SoldierDTO, listSoldiers } from "../api/soldiers";
import { RANGE_TYPE_LABELS, RANGE_EVENT_STATUS_LABELS } from "../utils/rangeLabels";

function localTodayIsoDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function RangesPage() {
  const [searchParams] = useSearchParams();
  const [selectedEventId, setSelectedEventId] = useState<string | null>(searchParams.get("event"));
  const [showPicker, setShowPicker] = useState(false);
  const [isReserveToggle, setIsReserveToggle] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newRangeType, setNewRangeType] = useState<RangeType>("laser");
  const [newDate, setNewDate] = useState("");
  const [newLocation, setNewLocation] = useState("");
  const [newRequiredCount, setNewRequiredCount] = useState(0);
  const [newReserveCount, setNewReserveCount] = useState(0);
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const nodeId = user?.hierarchy_node_id ?? null;
  const canManage = canPlan(user);

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
  const { data: soldiers } = useQuery({ queryKey: queryKeys.soldiers(), queryFn: listSoldiers });
  const soldierName = (id: string) => soldiers?.find((s) => s.id === id)?.full_name ?? id;

  async function handleRemoveAssignment(assignmentId: string) {
    if (!selectedEventId) return;
    await removeRangeAssignment(selectedEventId, assignmentId);
    queryClient.invalidateQueries({ queryKey: queryKeys.rangeEvent(selectedEventId) });
  }

  async function handleAddSoldier(soldier: SoldierDTO | null) {
    if (!soldier || !selectedEventId) return;
    await addRangeAssignment(selectedEventId, soldier.id, isReserveToggle);
    queryClient.invalidateQueries({ queryKey: queryKeys.rangeEvent(selectedEventId) });
    setShowPicker(false);
    setIsReserveToggle(false);
  }

  async function handleCreateEvent() {
    if (!nodeId) return;
    await createRangeEvent({
      hierarchy_node_id: nodeId as string,
      range_type: newRangeType,
      date: newDate,
      location: newLocation,
      required_count: newRequiredCount,
      reserve_count: newReserveCount,
    });
    queryClient.invalidateQueries({ queryKey: queryKeys.ranges() });
    setShowCreateForm(false);
    setNewRangeType("laser");
    setNewDate("");
    setNewLocation("");
    setNewRequiredCount(0);
    setNewReserveCount(0);
  }

  return (
    <Layout>
      <div className="space-y-4 p-4" dir="rtl">
        <div className="flex flex-wrap justify-between items-center gap-2">
          <h1 className="text-xl font-semibold">מטווחים</h1>
          {canManage && (
            <button
              data-testid="create-event-button"
              onClick={() => setShowCreateForm((v) => !v)}
              className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm font-medium hover:bg-indigo-700"
            >
              מטווח חדש
            </button>
          )}
        </div>

        {showCreateForm && (
          <form
            data-testid="create-event-form"
            onSubmit={(e) => {
              e.preventDefault();
              handleCreateEvent();
            }}
            className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3"
          >
            <div className="flex flex-wrap gap-3 items-end text-sm">
              <label className="flex flex-col gap-1">
                <span className="text-gray-700 dark:text-gray-300">סוג מטווח</span>
                <select
                  data-testid="new-range-type"
                  value={newRangeType}
                  onChange={(e) => setNewRangeType(e.target.value as RangeType)}
                  className="border rounded p-1.5 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                >
                  <option value="laser">{RANGE_TYPE_LABELS.laser}</option>
                  <option value="live">{RANGE_TYPE_LABELS.live}</option>
                  <option value="alal">{RANGE_TYPE_LABELS.alal}</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-gray-700 dark:text-gray-300">תאריך</span>
                <input
                  type="date"
                  data-testid="new-date"
                  value={newDate}
                  onChange={(e) => setNewDate(e.target.value)}
                  className="border rounded p-1.5 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-gray-700 dark:text-gray-300">מיקום</span>
                <input
                  type="text"
                  data-testid="new-location"
                  value={newLocation}
                  onChange={(e) => setNewLocation(e.target.value)}
                  className="border rounded p-1.5 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-gray-700 dark:text-gray-300">נדרש</span>
                <input
                  type="number"
                  min={0}
                  data-testid="new-required-count"
                  value={newRequiredCount}
                  onChange={(e) => setNewRequiredCount(Number(e.target.value))}
                  className="border rounded p-1.5 w-20 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-gray-700 dark:text-gray-300">רזרבה</span>
                <input
                  type="number"
                  min={0}
                  data-testid="new-reserve-count"
                  value={newReserveCount}
                  onChange={(e) => setNewReserveCount(Number(e.target.value))}
                  className="border rounded p-1.5 w-20 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                />
              </label>
              <button
                type="submit"
                className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700"
              >
                שמור
              </button>
            </div>
          </form>
        )}

        <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-700">
              <tr>
                <th className="text-right p-2 font-medium">תאריך</th>
                <th className="text-right p-2 font-medium">סוג</th>
                <th className="text-right p-2 font-medium">מיקום</th>
                <th className="text-right p-2 font-medium">סטטוס</th>
              </tr>
            </thead>
            <tbody>
              {(events ?? []).map((event: RangeEvent) => (
                <tr
                  key={event.id}
                  onClick={() => setSelectedEventId(event.id)}
                  className="border-t dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <td className="p-2" dir="ltr">{event.date}</td>
                  <td className="p-2">{RANGE_TYPE_LABELS[event.range_type] ?? event.range_type}</td>
                  <td className="p-2">{event.location}</td>
                  <td className="p-2">{RANGE_EVENT_STATUS_LABELS[event.status] ?? event.status}</td>
                </tr>
              ))}
              {(events ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="p-3 text-center text-gray-500 dark:text-gray-400">
                    אין מטווחים
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {selectedEvent && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
            <div className="flex flex-wrap justify-between items-center gap-2">
              <h2 className="text-lg font-semibold">{selectedEvent.location}</h2>
              {canManage && (
                <button
                  data-testid="add-soldier-button"
                  onClick={() => setShowPicker(true)}
                  className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm font-medium hover:bg-indigo-700"
                >
                  הוסף חייל
                </button>
              )}
            </div>

            {showPicker && (
              <div className="space-y-2 border rounded p-3 dark:border-gray-700">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    data-testid="reserve-toggle"
                    checked={isReserveToggle}
                    onChange={(e) => setIsReserveToggle(e.target.checked)}
                  />
                  שבץ כרזרבה
                </label>
                <SoldierSearchAutocomplete onSelect={handleAddSoldier} />
              </div>
            )}

            <ul className="divide-y dark:divide-gray-700">
              {selectedEvent.assignments.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <span>
                    <SoldierLink id={a.soldier_id} name={soldierName(a.soldier_id)} />
                    {a.is_reserve && (
                      <span className="text-xs text-amber-600 dark:text-amber-400 mr-1">(רזרבה)</span>
                    )}
                  </span>
                  {canManage && (
                    <button
                      onClick={() => handleRemoveAssignment(a.id)}
                      className="text-xs text-red-600 dark:text-red-400 hover:underline"
                    >
                      הסר
                    </button>
                  )}
                </li>
              ))}
              {selectedEvent.assignments.length === 0 && (
                <li className="py-2 text-sm text-gray-500 dark:text-gray-400">אין חיילים משובצים</li>
              )}
            </ul>

            {canManage && selectedEvent.date <= localTodayIsoDate() && (
              <RangeAttendancePanel
                eventId={selectedEvent.id}
                assignments={selectedEvent.assignments}
                soldierName={soldierName}
                onMarked={() => {
                  queryClient.invalidateQueries({ queryKey: queryKeys.rangeEvent(selectedEventId!) });
                  queryClient.invalidateQueries({ queryKey: queryKeys.ranges() });
                }}
              />
            )}
          </div>
        )}
      </div>
    </Layout>
  );
}
