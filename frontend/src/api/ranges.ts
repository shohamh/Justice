import { api } from "./client";

export type RangeType = "laser" | "live" | "alal";
export type RangeEventStatus = "planned" | "completed" | "cancelled";
export type RangeAttendanceStatus = "pending" | "present" | "no_show";

export interface RangeAssignment {
  id: string;
  soldier_id: string;
  is_reserve: boolean;
  attendance_status: RangeAttendanceStatus;
  note: string | null;
}

export interface RangeEvent {
  id: string;
  hierarchy_node_id: string;
  range_type: RangeType;
  date: string;
  location: string;
  required_count: number;
  reserve_count: number;
  status: RangeEventStatus;
  assignments: RangeAssignment[];
}

export interface CreateRangeEventBody {
  hierarchy_node_id: string;
  range_type: RangeType;
  date: string;
  location: string;
  required_count: number;
  reserve_count?: number;
  start_time?: string | null;
  end_time?: string | null;
  arrival_instructions?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  notes?: string | null;
}

export interface UpdateRangeEventBody {
  location?: string;
  required_count?: number;
  reserve_count?: number;
  arrival_instructions?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  notes?: string | null;
  cancel?: boolean;
}

export function getRanges(nodeId: string, dateFrom?: string, dateTo?: string): Promise<RangeEvent[]> {
  const params = new URLSearchParams({ node_id: nodeId });
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return api.get(`/ranges?${params.toString()}`).then((r) => r.data);
}

export function getRangeEvent(id: string): Promise<RangeEvent> {
  return api.get(`/ranges/${id}`).then((r) => r.data);
}

export function createRangeEvent(body: CreateRangeEventBody): Promise<RangeEvent> {
  return api.post("/ranges", body).then((r) => r.data);
}

export function updateRangeEvent(id: string, body: UpdateRangeEventBody): Promise<RangeEvent> {
  return api.patch(`/ranges/${id}`, body).then((r) => r.data);
}

export function addRangeAssignment(
  eventId: string, soldierId: string, isReserve: boolean,
): Promise<RangeAssignment> {
  return api.post(`/ranges/${eventId}/assignments`, { soldier_id: soldierId, is_reserve: isReserve }).then((r) => r.data);
}

export function removeRangeAssignment(eventId: string, assignmentId: string): Promise<void> {
  return api.delete(`/ranges/${eventId}/assignments/${assignmentId}`).then(() => undefined);
}

export function markRangeAttendance(
  eventId: string, assignmentId: string, status: RangeAttendanceStatus, note?: string,
): Promise<RangeAssignment> {
  return api.patch(`/ranges/${eventId}/assignments/${assignmentId}/attendance`, { status, note }).then((r) => r.data);
}
