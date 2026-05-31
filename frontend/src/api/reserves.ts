import { api } from "./client";

export interface DismissalRecord {
  id: string;
  duty_assignment_id: string;
  dismissed_from: string;
  dismissed_to: string;
  reason: string | null;
  created_at: string;
}

export interface PrimaryDetail {
  assignment_id: string;
  soldier_id: string;
  start_date: string;
  end_date: string;
  status: string;
  dismissals: DismissalRecord[];
  reserve_assignment_id: string | null;
  reserve_hierarchy_distance: number | null;
}

export interface ReserveDetail {
  assignment_id: string;
  soldier_id: string;
  start_date: string;
  end_date: string;
  status: string;
  called_up_from: string | null;
  called_up_to: string | null;
  primary_assignment_ids: string[];
}

export interface ShiftReserveDetail {
  primaries: PrimaryDetail[];
  reserves: ReserveDetail[];
}

export async function getShiftReserveDetail(shiftId: string): Promise<ShiftReserveDetail> {
  return (await api.get<ShiftReserveDetail>(`/shifts/${shiftId}/reserve-detail`)).data;
}

export async function callUpReserve(assignmentId: string, from_date: string, to_date: string): Promise<void> {
  await api.post(`/duty-assignments/${assignmentId}/call-up`, { from_date, to_date });
}

export async function dismissPrimary(
  assignmentId: string,
  from_date: string,
  to_date: string,
  reason?: string,
): Promise<DismissalRecord> {
  return (await api.post<DismissalRecord>(`/duty-assignments/${assignmentId}/dismissals`, { from_date, to_date, reason })).data;
}

export async function deleteDismissal(assignmentId: string, dismissalId: string): Promise<void> {
  await api.delete(`/duty-assignments/${assignmentId}/dismissals/${dismissalId}`);
}

export async function relinkReserve(shiftId: string, assignmentId: string, reserveAssignmentId: string): Promise<void> {
  await api.put(`/shifts/${shiftId}/duty-assignments/${assignmentId}/reserve-link`, { reserve_assignment_id: reserveAssignmentId });
}

export interface DismissAndReallocateRequest {
  primary_assignment_id: string;
  covering_reserve_assignment_id: string;
  from_date: string;
  to_date: string;
  reason?: string;
}

export interface ReallocationOut {
  primary_assignment_id: string;
  old_reserve_assignment_id: string;
  new_reserve_assignment_id: string | null;
  hierarchy_distance: number | null;
}

export interface DismissAndReallocateResponse {
  dismissal_id: string;
  covering_reserve: {
    assignment_id: string;
    called_up_from: string;
    called_up_to: string;
  };
  reallocations: ReallocationOut[];
}

export async function dismissAndReallocate(
  shiftId: string,
  body: DismissAndReallocateRequest,
): Promise<DismissAndReallocateResponse> {
  return (await api.post<DismissAndReallocateResponse>(`/shifts/${shiftId}/dismissals`, body)).data;
}
