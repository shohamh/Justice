import { api } from "./client";

export interface CalRow {
  soldier_id: string;
  full_name: string;
  assignments: { id: string; duty_type_id: string; duty_location_id: string; start_date: string; end_date: string }[];
}

export async function getUnitCalendar(nodeId: string, params?: { date_from?: string; date_to?: string }): Promise<CalRow[]> {
  return (await api.get<CalRow[]>(`/calendar/unit`, { params: { node_id: nodeId, ...params } })).data;
}
