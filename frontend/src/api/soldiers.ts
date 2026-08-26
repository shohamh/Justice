import { api } from "./client";
import type { RankTrack } from "./rankAdvancement";
import type { SoldierRef, WaitingOnRef } from "./myRequests";

export interface SoldierDTO {
  id: string;
  personal_number: string;
  full_name: string;
  role: string;
  hierarchy_node_id: string | null;
  phone: string | null;
  must_change_password: boolean;
  left_at: string | null;
  enrolled_at: string | null;
  gender: string | null;
  is_officer: boolean | null;
  is_career: boolean;
  rank: string | null;
  rank_track: RankTrack | null;
  next_rank_date: string | null;
  next_rank_date_overridden: boolean;
  can_edit_rank_advancement: boolean;
  bahad1_graduate: boolean;
  has_military_driving_license: boolean | null;
  military_driving_license_expiry: string | null;
  enlistment_date: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
  telegram_linked: boolean;
  email?: string | null;
  direct_commander_id?: string | null;
  direct_commander_name?: string | null;
  profile_picture_url?: string | null;
  food_type?: string | null;
  food_constraints?: string | null;
}

export interface OnboardResult extends SoldierDTO {
  temp_password: string | null;
}

/** Own field-update history rows share the enriched requests contract. */
export interface FieldUpdateDTO {
  requested_at: string;
  updated_at: string;
  waiting_on: WaitingOnRef | null;
  decided_by: SoldierRef | null;
  commander_approved_by: SoldierRef | null;
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  field_name: string;
  previous_value: string | null;
  new_value: string | null;
  status: "pending" | "approved" | "rejected";
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
  nearest_commander: { id: string; name: string } | null;
  nearest_duty_manager: { id: string; name: string } | null;
  can_approve: boolean;
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

export async function softDeleteSoldier(id: string, leftAt: string): Promise<void> {
  await api.delete(`/soldiers/${id}`, { params: { left_at: leftAt } });
}

export async function updateSoldier(
  id: string,
  input: { full_name?: string; phone?: string | null; enrolled_at?: string | null }
): Promise<SoldierDTO> {
  return (await api.patch<SoldierDTO>(`/soldiers/${id}`, input)).data;
}

export async function updateSoldierProfile(
  soldierId: string,
  fields: Partial<Pick<SoldierDTO, 'gender' | 'is_officer' | 'rank' | 'rank_track' | 'bahad1_graduate' | 'has_military_driving_license' | 'military_driving_license_expiry' | 'enlistment_date' | 'mandatory_end_date' | 'discharge_date' | 'last_mitvahim_date' | 'last_alal_date' | 'email' | 'profile_picture_url' | 'next_rank_date' | 'food_type' | 'food_constraints'>>
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

export async function getPendingFieldUpdateCount(): Promise<number> {
  const r = await api.get<{ count: number }>("/soldiers/field-updates/pending/count");
  return r.data.count;
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

export async function getRanks(): Promise<{ enlisted: string[]; officers: string[]; officer_academic: string[] }> {
  return (await api.get<{ enlisted: string[]; officers: string[]; officer_academic: string[] }>("/soldiers/ranks")).data;
}

export interface SoldierScoreDTO {
  soldier_id: string;
  active_days: number;
  cumulative_score: string;
  normalised_score: string;
}

export async function getSoldier(id: string): Promise<SoldierDTO> {
  return (await api.get<SoldierDTO>(`/soldiers/${id}`)).data;
}

export async function getSoldierScore(id: string): Promise<SoldierScoreDTO> {
  return (await api.get<SoldierScoreDTO>(`/soldiers/${id}/score`)).data;
}

export interface ReserveStats {
  used_days: number;
  max_days: number;
  window_days: number;
}

export async function getReserveStats(): Promise<ReserveStats> {
  return (await api.get<ReserveStats>("/soldiers/me/reserve-stats")).data;
}
