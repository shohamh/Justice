import { api as client } from "./client";

export interface NotificationDTO {
  id: string;
  soldier_id: string;
  title: string;
  body: string | null;
  type: string;
  reference_type: string | null;
  reference_id: string | null;
  is_read: boolean;
  created_at: string;
}


export const NOTIFICATION_TYPE_ICONS: Record<string, string> = {
  swap_offer: "🔄", swap_accepted: "✅", swap_rejected: "❌",
  exemption_approved: "✔️", exemption_rejected: "✖️",
  constraint_approved: "✔️", constraint_rejected: "✖️",
  assignment_created: "📋", assignment_removed: "🗑️",
  range_assignment_confirmed: "🎯", range_roster_changed: "👥",
  range_cancelled: "🚫", range_no_show: "⚠️",
  range_excusal_pending: "📩", range_excusal_approved: "✅", range_excusal_rejected: "❌",
  range_reserve_promoted: "⬆️", range_reserve_excused: "🛡️", range_excusal_no_backfill: "⚠️",
  range_reminder: "🔔", range_reminder_shortfall: "⚠️",
  score_adjusted: "⭐", announcement: "📢", system_announcement: "📣",
  algorithm_job_done: "🤖", algorithm_job_failed: "⚠️",
};

export const RANGE_NOTIFICATION_TYPES = [
  "range_assignment_confirmed", "range_roster_changed", "range_cancelled", "range_no_show",
  "range_excusal_pending", "range_excusal_approved", "range_excusal_rejected",
  "range_reserve_promoted", "range_reserve_excused", "range_excusal_no_backfill",
  "range_reminder", "range_reminder_shortfall",
] as const;

export interface PaginatedNotifications {
  items: NotificationDTO[];
  total: number;
}

export interface UnreadCount {
  count: number;
}

export interface NotificationPref {
  notification_type: string;
  in_app_enabled: boolean;
  push_enabled: boolean;
  email_enabled: boolean;
}

export interface SoldierBrief {
  id: string;
  full_name: string;
  personal_number: string;
}

export interface CommanderScope {
  id: string;
  hierarchy_node_id: string;
  node_name: string | null;
  depth: number;
  soldiers: SoldierBrief[];
}

export function getUnreadCount(): Promise<UnreadCount> {
  return client.get("/notifications/unread-count").then((r) => r.data);
}

export function listNotifications(params?: {
  is_read?: boolean;
  type?: string;
  offset?: number;
  limit?: number;
}): Promise<PaginatedNotifications> {
  return client.get("/notifications", { params }).then((r) => r.data);
}

export function markRead(id: string): Promise<NotificationDTO> {
  return client.patch(`/notifications/${id}/read`).then((r) => r.data);
}

export function markAllRead(): Promise<UnreadCount> {
  return client.patch("/notifications/read-all").then((r) => r.data);
}

export function deleteNotification(id: string): Promise<void> {
  return client.delete(`/notifications/${id}`);
}

export function getPreferences(): Promise<NotificationPref[]> {
  return client.get("/notifications/preferences").then((r) => r.data);
}

export function updatePreferences(preferences: NotificationPref[]): Promise<NotificationPref[]> {
  return client.put("/notifications/preferences", { preferences }).then((r) => r.data);
}

export function listCommanderScopes(): Promise<CommanderScope[]> {
  return client.get("/notifications/commander-scopes").then((r) => r.data);
}

export function addCommanderScope(hierarchy_node_id: string, depth: number = -1): Promise<CommanderScope> {
  return client.post("/notifications/commander-scopes", { hierarchy_node_id, depth }).then((r) => r.data);
}

export function removeCommanderScope(id: string): Promise<void> {
  return client.delete(`/notifications/commander-scopes/${id}`);
}
