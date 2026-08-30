import { api } from "./client";
import { isRecord, optionalArrayResponse, requiredObjectResponse } from "./responseGuards";

export interface AdminAuditLogEntryDTO {
  id: string;
  created_at: string;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  entity_exists: boolean | null;
  entity_link: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  context: Record<string, unknown> | null;
}

export interface AuditLogActorDTO {
  id: string;
  full_name: string;
}

export interface AuditLogFacetsDTO {
  actions: string[];
  entity_types: string[];
  actors: AuditLogActorDTO[];
}

export interface AdminAuditLogPageDTO {
  items: AdminAuditLogEntryDTO[];
  total: number;
  facets: AuditLogFacetsDTO;
}

export interface AdminAuditLogFilters {
  action?: string;
  entity_type?: string;
  actor_id?: string;
  created_from?: string;
  created_to?: string;
  limit: number;
  offset: number;
}

export async function listAdminAuditLogs(
  filters: AdminAuditLogFilters
): Promise<AdminAuditLogPageDTO> {
  const r = await api.get<unknown>("/admin/audit-logs", { params: filters });
  const data = requiredObjectResponse(r.data, "Invalid admin audit log response");
  const rawFacets = isRecord(data.facets) ? data.facets : {};
  return {
    ...(data as unknown as AdminAuditLogPageDTO),
    items: optionalArrayResponse<AdminAuditLogEntryDTO>(data.items),
    facets: {
      actions: optionalArrayResponse<string>(rawFacets.actions),
      entity_types: optionalArrayResponse<string>(rawFacets.entity_types),
      actors: optionalArrayResponse<AuditLogActorDTO>(rawFacets.actors),
    },
  };
}
