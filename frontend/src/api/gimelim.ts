import { api } from "./client";

export interface SoldierRef {
  id: string;
  name: string;
  rank: string | null;
}

export interface ShiftRef {
  shift_id: string;
  duty_type_name: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
}

export interface FutureAssignmentPreview {
  shift: ShiftRef;
  soldier_demoted: SoldierRef;
  demoted_assignment_id: string;
  c_existing_reserve_assignment_id: string | null;
  c_existing_reserve_soldier: SoldierRef | null;
}

export interface GimelimPreview {
  preview_token: string;
  preview_token_expires_at: string;
  current_shift: ShiftRef;
  soldier_a: SoldierRef;
  primary_assignment_id: string;
  reserve_assignment_id: string;
  reserve_soldier: SoldierRef;
  future_assignment: FutureAssignmentPreview | null;
  warnings: string[];
}

export interface GimelimCommitResult {
  dismissal_id: string;
  call_up_assignment_id: string;
  future_primary_assignment_id: string | null;
  future_demoted_assignment_id: string | null;
  notifications_queued: number;
}

export async function previewGimelim(
  shiftId: string,
  body: { primary_assignment_id: string; rest_days: number; reason?: string }
): Promise<GimelimPreview> {
  return (await api.post<GimelimPreview>(`/shifts/${shiftId}/gimelim/preview`, body)).data;
}

export async function commitGimelim(
  shiftId: string,
  previewToken: string
): Promise<GimelimCommitResult> {
  return (await api.post<GimelimCommitResult>(`/shifts/${shiftId}/gimelim/commit`, {
    preview_token: previewToken,
  })).data;
}
