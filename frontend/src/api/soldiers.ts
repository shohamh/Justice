import axios from "axios";

import { api } from "./client";
import type { RankTrack } from "./rankAdvancement";
import type { SoldierRef, WaitingOnRef } from "./myRequests";
import {
  isRecord,
  optionalArrayResponse,
  requiredArrayResponse,
  requiredObjectResponse,
  requiredStringArrayField,
} from "./responseGuards";

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
  can_request_unit_join_date?: boolean;
  bahad1_graduate: boolean;
  has_military_driving_license: boolean | null;
  military_driving_license_expiry: string | null;
  enlistment_date: string | null;
  unit_join_date: string | null;
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
  visibility?: "full" | "public";
  hierarchy_path?: string[];
}

export interface SoldierRosterItemDTO {
  id: string;
  personal_number: string;
  full_name: string;
  role: string;
  hierarchy_node_id: string | null;
  left_at: string | null;
  telegram_linked: boolean;
  is_commander: boolean;
  commander_node_name: string | null;
  hierarchy_path: string[];
}

export type SoldierRosterSort =
  | "full_name"
  | "personal_number"
  | "role"
  | "node"
  | "telegram";

export interface SoldierRosterPageDTO {
  items: SoldierRosterItemDTO[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface SoldierRosterRequest {
  cursor?: string;
  node_id?: string;
  direct_node_only?: boolean;
  search: string;
  sort: SoldierRosterSort;
  descending: boolean;
  role_order?: string;
  page_size: number;
  active_only?: boolean;
  signal?: AbortSignal;
}

export interface HakpazaSoldierRosterItemDTO {
  id: string;
  full_name: string;
  rank: string | null;
  next_shift_date: string | null;
  next_shift_type_name: string | null;
}

export interface HakpazaSoldierRosterPageDTO {
  items: HakpazaSoldierRosterItemDTO[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface HakpazaSoldierRosterRequest {
  as_of_date: string;
  search: string;
  page_size: number;
  cursor?: string;
  signal?: AbortSignal;
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
  commander_approved_at?: string | null;
  commander_approval_note?: string | null;
  duty_manager_approved_by?: SoldierRef | null;
  duty_manager_approved_at?: string | null;
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  field_name: string;
  previous_value: string | null;
  new_value: string | null;
  status: "pending" | "pending_commander" | "pending_duty_manager" | "approved" | "rejected" | "cancelled" | "superseded";
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
  nearest_commander: { id: string; name: string } | null;
  nearest_duty_manager: { id: string; name: string } | null;
  can_approve: boolean;
}

export async function listSoldiers(): Promise<SoldierDTO[]> {
  const data = (await api.get<unknown>("/soldiers")).data;
  return optionalArrayResponse<SoldierDTO>(data);
}

export interface SoldierNameDTO {
  id: string;
  full_name: string;
  personal_number?: string;
}

export async function lookupSoldierNames(ids: string[]): Promise<SoldierNameDTO[]> {
  const uniqueIds = [...new Set(ids)];
  const names: SoldierNameDTO[] = [];
  // Four bounded requests at a time; large jobs and range events cannot truncate names.
  for (let offset = 0; offset < uniqueIds.length; offset += 800) {
    const batch = uniqueIds.slice(offset, offset + 800);
    const chunks = [0, 200, 400, 600]
      .map(start => batch.slice(start, start + 200))
      .filter(chunk => chunk.length > 0);
    const results = await Promise.all(chunks.map(async chunk => {
      const data = (await api.post<unknown>("/soldiers/lookup/names", { ids: chunk })).data;
      return requiredArrayResponse<SoldierNameDTO>(data, "Invalid soldier names response");
    }));
    names.push(...results.flat());
  }
  return names;
}

export async function listSoldierRosterPage(
  request: SoldierRosterRequest,
): Promise<SoldierRosterPageDTO> {
  const { signal, ...query } = request;
  const payload = requiredObjectResponse(
    (await api.get<unknown>("/soldiers/roster", { params: query, signal })).data,
    "Invalid soldier roster response",
  );
  const items = requiredArrayResponse<SoldierRosterItemDTO>(
    payload.items,
    "Invalid soldier roster items",
  );
  if (typeof payload.has_more !== "boolean") {
    throw new Error("Invalid soldier roster paging state");
  }
  if (payload.next_cursor !== null && typeof payload.next_cursor !== "string") {
    throw new Error("Invalid soldier roster cursor");
  }
  return {
    items,
    next_cursor: payload.next_cursor,
    has_more: payload.has_more,
  };
}

export async function listHakpazaSoldierRosterPage(
  request: HakpazaSoldierRosterRequest,
): Promise<HakpazaSoldierRosterPageDTO> {
  const { signal, ...query } = request;
  const payload = requiredObjectResponse(
    (await api.get<unknown>("/soldiers/roster/hakpaza", { params: query, signal })).data,
    "Invalid Hakpaza soldier roster response",
  );
  const rawItems = requiredArrayResponse<unknown>(
    payload.items,
    "Invalid Hakpaza soldier roster items",
  );
  const items = rawItems.map((value) => {
    const row = requiredObjectResponse(
      value,
      "Invalid Hakpaza soldier roster item",
    );
    if (
      typeof row.id !== "string" ||
      typeof row.full_name !== "string" ||
      !(row.rank === null || typeof row.rank === "string") ||
      !(row.next_shift_date === null || typeof row.next_shift_date === "string") ||
      !(row.next_shift_type_name === null || typeof row.next_shift_type_name === "string")
    ) {
      throw new Error("Invalid Hakpaza soldier roster item");
    }
    return row as unknown as HakpazaSoldierRosterItemDTO;
  });
  if (typeof payload.has_more !== "boolean") {
    throw new Error("Invalid Hakpaza soldier roster paging state");
  }
  if (payload.next_cursor !== null && typeof payload.next_cursor !== "string") {
    throw new Error("Invalid Hakpaza soldier roster cursor");
  }
  if (payload.has_more && typeof payload.next_cursor !== "string") {
    throw new Error("Hakpaza soldier roster omitted its continuation cursor");
  }
  return {
    items,
    next_cursor: payload.next_cursor,
    has_more: payload.has_more,
  };
}

export function isStaleHakpazaSoldierRosterCursorError(error: unknown): boolean {
  return (
    axios.isAxiosError(error) &&
    error.response?.status === 409 &&
    isRecord(error.response.data) &&
    (error.response.data.detail === "stale_cursor" ||
      error.response.data.detail === "roster_changed")
  );
}

export async function lookupSoldierByPersonalNumber(
  personalNumber: string,
): Promise<SoldierRosterItemDTO | null> {
  const data = (await api.get<unknown>("/soldiers/lookup/personal-number", {
    params: { personal_number: personalNumber },
  })).data;
  if (data === null) return null;
  return requiredObjectResponse(
    data,
    "Invalid soldier personal-number lookup response",
  ) as unknown as SoldierRosterItemDTO;
}

export function isStaleSoldierRosterCursorError(error: unknown): boolean {
  return (
    axios.isAxiosError(error) &&
    error.response?.status === 409 &&
    isRecord(error.response.data) &&
    error.response.data.detail === "stale_cursor"
  );
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

export async function promoteSoldierToAdmin(id: string, currentPassword: string): Promise<SoldierDTO> {
  return (await api.post<SoldierDTO>(`/soldiers/${id}/promote-admin`, {
    current_password: currentPassword,
    confirm: true,
  })).data;
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
  const data = (await api.get<unknown>(`/soldiers/${soldierId}/field-updates`)).data;
  return optionalArrayResponse<FieldUpdateDTO>(data);
}

export async function getPendingFieldUpdateCount(): Promise<number> {
  const r = await api.get<{ count: number }>("/soldiers/field-updates/pending/count");
  return r.data.count;
}

export async function listPendingFieldUpdates(): Promise<FieldUpdateDTO[]> {
  const data = (await api.get<unknown>(`/soldiers/field-updates/pending`)).data;
  return requiredArrayResponse<FieldUpdateDTO>(data, "Invalid pending field updates response");
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
  const data = requiredObjectResponse((await api.get<unknown>("/soldiers/ranks")).data, "Invalid soldier ranks response");
  return {
    ...data,
    enlisted: requiredStringArrayField(data.enlisted, "Invalid soldier ranks response"),
    officers: requiredStringArrayField(data.officers, "Invalid soldier ranks response"),
    officer_academic: requiredStringArrayField(data.officer_academic, "Invalid soldier ranks response"),
  } as { enlisted: string[]; officers: string[]; officer_academic: string[] };
}

export interface SoldierScoreDTO {
  soldier_id: string;
  active_days: number;
  cumulative_score: string;
  normalised_score: string;
}

export async function getSoldier(id: string): Promise<SoldierDTO> {
  const data = (await api.get<unknown>(`/soldiers/${id}`)).data;
  if (
    !isRecord(data) ||
    typeof data.id !== "string" ||
    typeof data.personal_number !== "string" ||
    typeof data.full_name !== "string"
  ) {
    throw new Error("Invalid soldier response");
  }
  return data as unknown as SoldierDTO;
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
