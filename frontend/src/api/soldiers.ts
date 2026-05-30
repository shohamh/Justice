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
  gender: string | null;
  is_officer: boolean | null;
  rank: string | null;
  bahad1_graduate: boolean;
  enlistment_date: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
}

export interface OnboardResult extends SoldierDTO {
  temp_password: string | null;
}

export interface FieldUpdateDTO {
  id: string;
  soldier_id: string;
  field_name: string;
  new_value: string;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
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

export async function updateSoldier(
  id: string,
  input: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null }
): Promise<SoldierDTO> {
  return (await api.patch<SoldierDTO>(`/soldiers/${id}`, input)).data;
}

export async function updateSoldierProfile(
  soldierId: string,
  fields: Partial<Record<string, string | boolean | null>>
): Promise<SoldierDTO> {
  return (await api.patch<SoldierDTO>(`/soldiers/${soldierId}/profile`, fields)).data;
}

export async function submitFieldUpdate(
  soldierId: string,
  fieldName: string,
  newValue: string
): Promise<FieldUpdateDTO> {
  return (await api.post<FieldUpdateDTO>(`/soldiers/${soldierId}/field-updates`, {
    field_name: fieldName,
    new_value: newValue,
  })).data;
}

export async function listFieldUpdates(soldierId: string): Promise<FieldUpdateDTO[]> {
  return (await api.get<FieldUpdateDTO[]>(`/soldiers/${soldierId}/field-updates`)).data;
}

export async function listPendingFieldUpdates(): Promise<FieldUpdateDTO[]> {
  return (await api.get<FieldUpdateDTO[]>(`/soldiers/field-updates/pending`)).data;
}

export async function approveFieldUpdate(
  soldierId: string,
  updateId: string,
  decisionNote?: string
): Promise<FieldUpdateDTO> {
  return (await api.post<FieldUpdateDTO>(
    `/soldiers/${soldierId}/field-updates/${updateId}/approve`,
    { decision_note: decisionNote ?? null }
  )).data;
}

export async function rejectFieldUpdate(
  soldierId: string,
  updateId: string,
  decisionNote?: string
): Promise<FieldUpdateDTO> {
  return (await api.post<FieldUpdateDTO>(
    `/soldiers/${soldierId}/field-updates/${updateId}/reject`,
    { decision_note: decisionNote ?? null }
  )).data;
}

export async function getRanks(): Promise<{ enlisted: string[]; officers: string[] }> {
  return (await api.get<{ enlisted: string[]; officers: string[] }>("/soldiers/ranks")).data;
}
