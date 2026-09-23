import { api } from "./client";
import { requiredObjectResponse, optionalArrayResponse } from "./responseGuards";

export interface HeldForReviewItemDTO {
  id: string;
  personal_number: string;
  review_reason: string | null;
  last_synced_at: string | null;
}

export async function listHeldForReview(): Promise<{ items: HeldForReviewItemDTO[] }> {
  const r = await api.get<unknown>("/admin/hr-sync/held-for-review");
  const data = requiredObjectResponse(r.data, "Invalid held-for-review response");
  return { items: optionalArrayResponse<HeldForReviewItemDTO>(data.items) };
}

export async function dismissHeldForReview(profileId: string): Promise<HeldForReviewItemDTO> {
  const r = await api.post<unknown>(`/admin/hr-sync/held-for-review/${profileId}/dismiss`);
  return requiredObjectResponse(r.data, "Invalid dismiss response") as unknown as HeldForReviewItemDTO;
}

export interface DivergenceItemDTO {
  id: string;
  soldier_hr_profile_id: string;
  field_name: string;
  hr_value: unknown;
  local_value: unknown;
  created_at: string;
}

export async function listDivergences(): Promise<{ items: DivergenceItemDTO[] }> {
  const r = await api.get<unknown>("/admin/hr-sync/divergences");
  const data = requiredObjectResponse(r.data, "Invalid divergences response");
  return { items: optionalArrayResponse<DivergenceItemDTO>(data.items) };
}

export async function clearFieldOverride(
  profileId: string, fieldName: string
): Promise<HeldForReviewItemDTO> {
  const r = await api.post<unknown>(
    `/admin/hr-sync/divergences/${profileId}/clear-override`, { field_name: fieldName }
  );
  return requiredObjectResponse(r.data, "Invalid clear-override response") as unknown as HeldForReviewItemDTO;
}

export interface VanishedItemDTO {
  id: string;
  personal_number: string;
  last_synced_at: string | null;
}

export async function listVanished(): Promise<{ items: VanishedItemDTO[] }> {
  const r = await api.get<unknown>("/admin/hr-sync/vanished");
  const data = requiredObjectResponse(r.data, "Invalid vanished response");
  return { items: optionalArrayResponse<VanishedItemDTO>(data.items) };
}

export interface RankConflictItemDTO {
  id: string;
  soldier_id: string;
  old_rank: string | null;
  new_rank: string | null;
  triggered_by_worker_decision: boolean;
  non_sequential_jump: boolean;
  created_at: string;
}

export async function listRankConflicts(): Promise<{ items: RankConflictItemDTO[] }> {
  const r = await api.get<unknown>("/admin/hr-sync/rank-conflicts");
  const data = requiredObjectResponse(r.data, "Invalid rank-conflicts response");
  return { items: optionalArrayResponse<RankConflictItemDTO>(data.items) };
}

export interface SyncErrorDTO {
  personal_number: string;
  error_message: string;
}

export interface PersonSyncRunDTO {
  id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  total_fetched: number;
  created_count: number;
  updated_count: number;
  held_count: number;
  vanished_count: number;
  error_count: number;
  error_message: string | null;
  errors: SyncErrorDTO[];
}

export interface HierarchySyncRunDTO {
  id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  created_count: number;
  matched_count: number;
  held_count: number;
  error_message: string | null;
}

export async function listSyncRuns(): Promise<{
  person_syncs: PersonSyncRunDTO[];
  hierarchy_syncs: HierarchySyncRunDTO[];
}> {
  const r = await api.get<unknown>("/admin/hr-sync/runs");
  const data = requiredObjectResponse(r.data, "Invalid sync-runs response");
  return {
    person_syncs: optionalArrayResponse<PersonSyncRunDTO>(data.person_syncs),
    hierarchy_syncs: optionalArrayResponse<HierarchySyncRunDTO>(data.hierarchy_syncs),
  };
}

export interface RunNowResultDTO {
  hierarchy_sync_id: string | null;
  person_sync_id: string | null;
}

export async function runSyncNow(): Promise<RunNowResultDTO> {
  const r = await api.post<unknown>("/admin/hr-sync/run-now");
  return requiredObjectResponse(r.data, "Invalid run-now response") as unknown as RunNowResultDTO;
}
