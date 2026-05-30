import { api } from "./client";

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
