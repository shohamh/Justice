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
