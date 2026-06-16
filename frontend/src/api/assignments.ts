import { api } from "./client";

export interface Assignment {
  id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  status: string;
  notes: string | null;
}

export interface EffectiveDuty {
  assignment_id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  shift_id?: string | null;
}

export async function listAssignments(soldierId: string, params?: { date_from?: string; date_to?: string }): Promise<Assignment[]> {
  return (await api.get<Assignment[]>(`/assignments`, { params: { soldier_id: soldierId, ...params } })).data;
}

export async function listEffectiveDuties(soldierId: string, params?: { date_from?: string; date_to?: string }): Promise<EffectiveDuty[]> {
  return (await api.get<EffectiveDuty[]>(`/assignments/effective`, { params: { soldier_id: soldierId, ...params } })).data;
}
export async function createAssignment(input: {
  soldier_id: string; duty_type_id: string; duty_location_id: string; start_date: string; end_date: string; duty_shift_id?: string | null; notes?: string | null; is_reserve?: boolean;
}): Promise<Assignment> {
  return (await api.post<Assignment>(`/assignments`, input)).data;
}

export interface ShiftCandidate {
  soldier_id: string;
  full_name: string;
  personal_number: string;
  effort: number;
  blocked: boolean;
  blocked_reason: "constraint" | "assignment" | null;
  hierarchy_path_ids: string[];
}

export async function getShiftCandidates(shiftId: string): Promise<ShiftCandidate[]> {
  return (await api.get<ShiftCandidate[]>(`/shifts/${shiftId}/candidates`)).data;
}
export async function cancelAssignment(id: string, reason: string): Promise<Assignment> {
  return (await api.post<Assignment>(`/assignments/${id}/cancel`, { reason })).data;
}
export async function setOverride(id: string, day: string, input: { effective_soldier_id: string | null; reason: string }): Promise<void> {
  await api.put(`/assignments/${id}/overrides/${day}`, input);
}
export async function clearOverride(id: string, day: string): Promise<void> {
  await api.delete(`/assignments/${id}/overrides/${day}`);
}

export async function clearAllAssignments(): Promise<void> {
  await api.delete("/assignments");
}
