import { api } from "./client";

export interface AdminAuditLogEntryDTO {
  id: string;
  created_at: string;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
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
  const r = await api.get<AdminAuditLogPageDTO>("/admin/audit-logs", { params: filters });
  return r.data;
}
