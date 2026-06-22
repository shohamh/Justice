import { api } from "./client";

export interface Exemption {
  id: string;
  soldier_id: string;
  exemption_type_id: string;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  granted_by: string | null;
}

export async function listExemptions(soldierId: string): Promise<Exemption[]> {
  return (await api.get<Exemption[]>(`/soldiers/${soldierId}/exemptions`)).data;
}
export async function grantExemption(soldierId: string, input: { exemption_type_id: string; start_date: string; end_date?: string | null; reason?: string | null }): Promise<Exemption> {
  return (await api.post<Exemption>(`/soldiers/${soldierId}/exemptions`, input)).data;
}
export async function revokeExemption(soldierId: string, exemptionId: string): Promise<void> {
  await api.delete(`/soldiers/${soldierId}/exemptions/${exemptionId}`);
}

export interface ExemptionRequest {
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  exemption_type_id: string;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decision_note: string | null;
  created_at: string;
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

export async function approveExemptionRequest(
  id: string,
  note?: string | null,
): Promise<ExemptionRequest> {
  return (await api.post<ExemptionRequest>(`/exemption-requests/${id}/approve`, { decision_note: note || null })).data;
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
