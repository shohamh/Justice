import { api } from "./client";

export interface Exemption {
  id: string;
  soldier_id: string;
  exemption_type_id: string | null;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  granted_by: string | null;
  revoke_reason: string | null;
  revoked_by_name: string | null;
}

export interface ExemptionSummaryItem {
  id: string;
  exemption_type_name: string;
  is_global: boolean;
  start_date: string;
  end_date: string | null;
}

export interface ExemptionDetail {
  id: string;
  exemption_type_name: string;
  is_global: boolean;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  granted_by_name: string | null;
}

export async function getExemptionDetail(soldierId: string, exemptionId: string): Promise<ExemptionDetail> {
  return (await api.get<ExemptionDetail>(`/soldiers/${soldierId}/exemptions/${exemptionId}`)).data;
}

export async function listExemptions(soldierId: string): Promise<Exemption[]> {
  return (await api.get<Exemption[]>(`/soldiers/${soldierId}/exemptions`)).data;
}
export async function grantExemption(soldierId: string, input: { exemption_type_id: string; start_date: string; end_date?: string | null; reason?: string | null }): Promise<Exemption> {
  return (await api.post<Exemption>(`/soldiers/${soldierId}/exemptions`, input)).data;
}
export async function revokeExemption(soldierId: string, exemptionId: string, reason: string): Promise<void> {
  await api.delete(`/soldiers/${soldierId}/exemptions/${exemptionId}`, { data: { reason } });
}

export interface ExemptionRequest {
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  exemption_type_id: string | null;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  status: "pending_commander" | "pending_duty_manager" | "approved" | "rejected";
  enrollment_request_id: string | null;
  decided_by: string | null;
  decision_note: string | null;
  created_at: string;
  files: ExemptionFile[];
}

export async function patchExemptionRequest(
  id: string,
  data: {
    exemption_type_id?: string;
    start_date?: string;
    end_date?: string | null;
    reason?: string | null;
  }
): Promise<ExemptionRequest> {
  const r = await api.patch<ExemptionRequest>(`/exemption-requests/${id}`, data);
  return r.data;
}

export async function listMyExemptionRequests(): Promise<ExemptionRequest[]> {
  return (await api.get<ExemptionRequest[]>("/me/exemption-requests")).data;
}

export async function submitExemptionRequest(input: {
  exemption_type_id: string;
  start_date: string;
  end_date?: string | null;
  reason?: string | null;
}): Promise<ExemptionRequest> {
  return (await api.post<ExemptionRequest>("/me/exemption-requests", input)).data;
}

export async function listPendingExemptionRequests(): Promise<ExemptionRequest[]> {
  return (await api.get<ExemptionRequest[]>("/exemption-requests/pending")).data;
}

export async function getPendingExemptionCount(): Promise<number> {
  const r = await api.get<{ count: number }>("/exemption-requests/pending/count");
  return r.data.count;
}

export async function approveExemptionRequestCommanderStep(requestId: string): Promise<void> {
  await api.post(`/exemption-requests/${requestId}/approve-commander`, {});
}

export async function approveExemptionRequestDutyManagerStep(requestId: string, decisionNote?: string): Promise<void> {
  await api.post(`/exemption-requests/${requestId}/approve-duty-manager`, { decision_note: decisionNote ?? null });
}

export async function rejectExemptionRequest(
  id: string,
  note: string,
): Promise<ExemptionRequest> {
  return (await api.post<ExemptionRequest>(`/exemption-requests/${id}/reject`, { decision_note: note })).data;
}

export interface ExemptionFile {
  id: string;
  file_name: string;
  content_type: string;
  created_at: string;
}

export async function uploadExemptionFile(requestId: string, file: File): Promise<ExemptionFile> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await api.post<ExemptionFile>(
    `/me/exemption-requests/${requestId}/files`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return res.data;
}

export async function listExemptionFiles(requestId: string): Promise<ExemptionFile[]> {
  const res = await api.get<ExemptionFile[]>(`/exemption-requests/${requestId}/files`);
  return res.data;
}

export function exemptionFileDownloadUrl(requestId: string, fileId: string): string {
  return `/api/exemption-requests/${requestId}/files/${fileId}`;
}

export async function grantCommanderExemption(soldierId: string, input: {
  exemption_type_id: string; start_date: string; end_date?: string | null; reason: string;
}): Promise<void> {
  await api.post(`/soldiers/${soldierId}/exemptions/commander-exemption`, input);
}

export async function escalateCommanderExemption(soldierId: string, input: {
  official_exemption_type_id: string;
  commander_exemption_type_id?: string;
  start_date: string;
  end_date?: string | null;
  reason: string;
  apply_immediately: boolean;
}): Promise<ExemptionRequest> {
  return (await api.post<ExemptionRequest>(`/soldiers/${soldierId}/exemptions/commander-escalate`, input)).data;
}

export async function listExemptionRequestsForSoldier(soldierId: string): Promise<ExemptionRequest[]> {
  return (await api.get<ExemptionRequest[]>(`/soldiers/${soldierId}/exemption-requests`)).data;
}
