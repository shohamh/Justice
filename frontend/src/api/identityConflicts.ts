import { api } from "./client";
import { optionalArrayResponse, requiredObjectResponse } from "./responseGuards";

export type IdentityConflictStatus = "open" | "resolved" | "dismissed";

export interface IdentityConflictCandidateDTO {
  soldier_id: string;
  full_name: string | null;
  personal_number: string | null;
  email_masked: string | null;
  matched_fields: string[];
  active: boolean;
}

export interface IdentityConflictDTO {
  id: string;
  source: string;
  status: IdentityConflictStatus;
  ad_username: string;
  personal_number: string | null;
  created_at: string;
  resolved_at: string | null;
  chosen_soldier_id: string | null;
  resolution_note: string | null;
  candidates: IdentityConflictCandidateDTO[];
}

function parseConflict(value: unknown): IdentityConflictDTO {
  const data = requiredObjectResponse(value, "Invalid identity conflict response");
  return {
    ...(data as unknown as IdentityConflictDTO),
    candidates: optionalArrayResponse<IdentityConflictCandidateDTO>(data.candidates),
  };
}

export async function listIdentityConflicts(
  status: IdentityConflictStatus = "open",
): Promise<{ items: IdentityConflictDTO[] }> {
  const r = await api.get<unknown>("/admin/identity-conflicts", { params: { status } });
  const data = requiredObjectResponse(r.data, "Invalid identity conflicts response");
  return { items: optionalArrayResponse<unknown>(data.items).map(parseConflict) };
}

export async function resolveIdentityConflict(conflictId: string, soldierId: string): Promise<IdentityConflictDTO> {
  const r = await api.post<unknown>(`/admin/identity-conflicts/${conflictId}/resolve`, { soldier_id: soldierId });
  return parseConflict(r.data);
}

export async function dismissIdentityConflict(conflictId: string, reason: string): Promise<IdentityConflictDTO> {
  const r = await api.post<unknown>(`/admin/identity-conflicts/${conflictId}/dismiss`, { reason });
  return parseConflict(r.data);
}
