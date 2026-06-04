import { api } from "./client";

export interface EnrollmentRequestDTO {
  id: string;
  soldier_id: string;
  requested_node_id: string;
  status: string;
  decided_by: string | null;
  decision_note: string | null;
}

export async function listPendingEnrollments(): Promise<EnrollmentRequestDTO[]> {
  const r = await api.get<EnrollmentRequestDTO[]>("/enrollment-requests/pending");
  return r.data;
}

export async function approveEnrollment(id: string, decision_note?: string): Promise<void> {
  await api.post(`/enrollment-requests/${id}/approve`, { decision_note: decision_note ?? null });
}

export async function rejectEnrollment(id: string, decision_note: string): Promise<void> {
  await api.post(`/enrollment-requests/${id}/reject`, { decision_note });
}
