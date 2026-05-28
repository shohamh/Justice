import { api } from "./client";

export interface SoldierDTO {
  id: string;
  personal_number: string;
  full_name: string;
  role: string;
  hierarchy_node_id: string | null;
  phone: string | null;
  must_change_password: boolean;
  left_at: string | null;
}

export interface OnboardResult extends SoldierDTO {
  temp_password: string | null;
}

export async function listSoldiers(): Promise<SoldierDTO[]> {
  return (await api.get<SoldierDTO[]>("/soldiers")).data;
}

export async function onboardSoldier(input: {
  personal_number: string;
  full_name: string;
  hierarchy_node_id: string | null;
  phone?: string | null;
  password?: string | null;
}): Promise<OnboardResult> {
  return (await api.post<OnboardResult>("/soldiers", input)).data;
}

export async function resetSoldierPassword(id: string): Promise<{ temp_password: string }> {
  return (await api.post<{ temp_password: string }>(`/soldiers/${id}/reset-password`)).data;
}

export async function softDeleteSoldier(id: string): Promise<void> {
  await api.delete(`/soldiers/${id}`);
}

export async function assignRole(id: string, role: string): Promise<SoldierDTO> {
  return (await api.post<SoldierDTO>(`/soldiers/${id}/role`, { role })).data;
}
