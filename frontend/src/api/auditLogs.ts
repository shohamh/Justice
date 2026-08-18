import { api } from "./client";

export type AuditLogEntityType = "soldier_exemption" | "personal_constraint";

export interface AuditLogEntry {
  id: string;
  action: string;
  actor_id: string | null;
  actor_name: string | null;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  context: Record<string, unknown> | null;
  created_at: string;
}

export async function listAuditLogs(
  entityType: AuditLogEntityType,
  entityId: string,
): Promise<AuditLogEntry[]> {
  return (
    await api.get<AuditLogEntry[]>("/audit-logs", {
      params: { entity_type: entityType, entity_id: entityId },
    })
  ).data;
}
