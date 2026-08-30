import { api } from "./client";
import type { RankTrack } from "./rankAdvancement";
import { optionalArrayResponse } from "./responseGuards";

export interface EnrollmentExemptionDTO {
  id: string;
  exemption_type_id: string | null;
  start_date: string | null;
  end_date: string | null;
  reason: string | null;
  status: string;
}

export interface EnrollmentRequestDTO {
  id: string;
  soldier_id: string;
  soldier_name: string;
  soldier_personal_number: string;
  requested_node_id: string;
  requested_node_name: string | null;
  status: string;
  decided_by: string | null;
  decision_note: string | null;
  phone: string | null;
  email: string | null;
  rank: string | null;
  rank_track: RankTrack | null;
  is_officer: boolean | null;
  is_career: boolean;
  can_edit_rank_advancement: boolean;
  gender: string | null;
  enlistment_date: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
  exemption_requests: EnrollmentExemptionDTO[];
  nearest_commander: { id: string; name: string } | null;
  nearest_duty_manager: { id: string; name: string } | null;
}

export async function listPendingEnrollments(): Promise<EnrollmentRequestDTO[]> {
  const r = await api.get<unknown>("/enrollment-requests/pending");
  return optionalArrayResponse<EnrollmentRequestDTO>(r.data);
}

export async function approveEnrollment(id: string, decision_note?: string): Promise<void> {
  await api.post(`/enrollment-requests/${id}/approve`, { decision_note: decision_note ?? null });
}

export async function rejectEnrollment(id: string, decision_note: string): Promise<void> {
  await api.post(`/enrollment-requests/${id}/reject`, { decision_note });
}

export async function patchEnrollment(
  id: string,
  data: {
    full_name?: string;
    personal_number?: string;
    requested_node_id?: string;
    phone?: string | null;
    email?: string | null;
    rank?: string | null;
    rank_track?: RankTrack | null;
    is_officer?: boolean | null;
    gender?: string | null;
    enlistment_date?: string | null;
    mandatory_end_date?: string | null;
    discharge_date?: string | null;
    last_mitvahim_date?: string | null;
    last_alal_date?: string | null;
  }
): Promise<EnrollmentRequestDTO> {
  const r = await api.patch<EnrollmentRequestDTO>(`/enrollment-requests/${id}`, data);
  return r.data;
}
