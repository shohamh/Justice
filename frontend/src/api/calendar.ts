import { api } from "./client";

// Old types (still used by UnitCalendar)
export interface CalAssignment {
  assignment_id: string;
  duty_type_id: string;
  duty_type_name: string;
  duty_type_color: string;
  duty_location_id: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
}

export interface CalRow {
  soldier_id: string;
  full_name: string;
  hierarchy_node_id: string | null;
  assignments: CalAssignment[];
}

export async function getUnitCalendar(nodeId: string, params?: { date_from?: string; date_to?: string }): Promise<CalRow[]> {
  return (await api.get<CalRow[]>(`/calendar/unit`, { params: { node_id: nodeId, ...params } })).data;
}

// New shift-based calendar types
export interface CalendarShiftAssigneeDismissal {
  id: string;
  dismissed_from: string;
  dismissed_to: string;
  reason: string | null;
}

export interface CalendarShiftAssignee {
  assignment_id: string;
  soldier_id: string;
  soldier_name: string;
  hierarchy_label: string | null;
  is_reserve: boolean;
  profile_picture_url: string | null;
  dismissals: CalendarShiftAssigneeDismissal[];
  reserve_assignment_id: string | null;
  reserve_hierarchy_distance: number | null;
  called_up_from: string | null;
  called_up_to: string | null;
  primary_assignment_ids: string[];
  hierarchy_path_ids: string[];
}

export async function dismissReserve(
  assignmentId: string,
  body: { from_date: string; to_date: string; reason?: string; covering_reserve_assignment_id?: string },
): Promise<void> {
  await import("./client").then(({ api }) =>
    api.post(`/duty-assignments/${assignmentId}/reserve-dismissals`, body)
  );
}

export interface CalendarShift {
  id: string;
  duty_type_id: string;
  duty_type_name: string;
  duty_type_color: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
  start_time: string;
  end_time: string;
  start_at: string;
  end_at: string;
  required_count: number;
  assigned_count: number;
  fill_status: string;
  reserve_count: number;
  assignees: CalendarShiftAssignee[];
  swap_request_count?: number;
}

export interface CalendarShiftsResponse {
  shifts: CalendarShift[];
}

export async function getCalendarShifts(
  nodeId: string,
  params?: { date_from?: string; date_to?: string },
): Promise<CalendarShiftsResponse> {
  return (await api.get<CalendarShiftsResponse>("/calendar/shifts", { params: { node_id: nodeId, ...params } })).data;
}

export async function getCalendarShift(shiftId: string): Promise<CalendarShift> {
  return (await api.get<CalendarShift>(`/calendar/shifts/${shiftId}`)).data;
}
