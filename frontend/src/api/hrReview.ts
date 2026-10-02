import { api } from "./client";
import { requiredObjectResponse, optionalArrayResponse } from "./responseGuards";

export interface HeldForReviewItemDTO {
  id: string;
  personal_number: string;
  review_reason: string | null;
  last_synced_at: string | null;
  raw_dto: Record<string, unknown> | null;
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
  soldier_full_name: string | null;
  soldier_personal_number: string | null;
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
  soldier_full_name: string | null;
  soldier_personal_number: string | null;
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

// ---- HR identity conflicts (duplicate personal numbers / colliding identities) ----

export type HrIdentityConflictStatus = "open" | "acknowledged" | "resolved";

export interface HrIdentityCandidateDTO {
  index: number;
  key_type: string | null;
  key_value: string | null;
  /** Raw HR record, camelCase aliases as HR sends them. */
  payload: Record<string, unknown>;
  is_applied: boolean;
  choosable: boolean;
  /** Backend code explaining why this candidate cannot be chosen. */
  invalid_reason: string | null;
}

export interface HrPreferredRecordDTO {
  personal_number: string;
  key_type: string;
  key_value: string;
  chosen_by: string | null;
  chosen_by_name: string | null;
  chosen_at: string;
}

export interface HrCollidingSoldierDTO {
  soldier_id: string;
  full_name: string | null;
  personal_number: string | null;
}

export interface HrIdentityConflictDTO {
  id: string;
  personal_number: string;
  kind: string;
  reason: string;
  status: HrIdentityConflictStatus;
  applied_index: number | null;
  chosen_index: number | null;
  candidates: HrIdentityCandidateDTO[];
  colliding_soldiers: HrCollidingSoldierDTO[];
  preferred_record: HrPreferredRecordDTO | null;
  hr_person_sync_id: string | null;
  created_at: string;
  last_seen_at: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

function parseHrConflict(value: unknown): HrIdentityConflictDTO {
  const data = requiredObjectResponse(value, "Invalid identity conflict response");
  return {
    ...(data as unknown as HrIdentityConflictDTO),
    candidates: optionalArrayResponse<HrIdentityCandidateDTO>(data.candidates),
    colliding_soldiers: optionalArrayResponse<HrCollidingSoldierDTO>(data.colliding_soldiers),
    preferred_record: (data.preferred_record ?? null) as HrPreferredRecordDTO | null,
  };
}

export async function listHrIdentityConflicts(
  status: HrIdentityConflictStatus | "all" = "open",
): Promise<{ items: HrIdentityConflictDTO[] }> {
  const r = await api.get<unknown>("/admin/hr-sync/identity-conflicts", { params: { status } });
  const data = requiredObjectResponse(r.data, "Invalid identity-conflicts response");
  return { items: optionalArrayResponse<unknown>(data.items).map(parseHrConflict) };
}

export async function acknowledgeHrIdentityConflict(conflictId: string): Promise<HrIdentityConflictDTO> {
  const r = await api.post<unknown>(`/admin/hr-sync/identity-conflicts/${conflictId}/acknowledge`);
  return parseHrConflict(r.data);
}

export async function chooseHrIdentityCandidate(
  conflictId: string, candidateIndex: number,
): Promise<HrIdentityConflictDTO> {
  const r = await api.post<unknown>(
    `/admin/hr-sync/identity-conflicts/${conflictId}/choose`, { candidate_index: candidateIndex },
  );
  return parseHrConflict(r.data);
}

export async function listHrPreferredRecords(): Promise<{ items: HrPreferredRecordDTO[] }> {
  const r = await api.get<unknown>("/admin/hr-sync/preferred-records");
  const data = requiredObjectResponse(r.data, "Invalid preferred-records response");
  return { items: optionalArrayResponse<HrPreferredRecordDTO>(data.items) };
}

export async function clearHrPreferredRecord(personalNumber: string): Promise<void> {
  await api.delete(`/admin/hr-sync/preferred-records/${encodeURIComponent(personalNumber)}`);
}
