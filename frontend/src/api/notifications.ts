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
  metadata: Record<string, unknown> | null;
  sender_name?: string | null;
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
  bug_report_comment: "💬",
};

// Notification types sent only to a commander/duty-manager being asked to
// decide something (never to the requesting soldier) — see
// notify_commanders_of_request / notify_duty_managers_of_request /
// cascade_to_commanders callers on the backend — so they always route to the
// Approvals page, distinct from the *_approved/*_rejected outcome types
// below, which go to the soldier and route to their own request list.
const PROFILE_LINK_TYPES = new Set([
  "rank_advanced", "rank_advancement_soon",
  "mitvahim_expiring_soon", "mitvahim_expired",
  "alal_expiring_soon", "alal_expired",
]);

// Shared reference_type -> route mapping used by both NotificationBell (the
// dropdown) and NotificationsPage (the full list), so the two surfaces can't
// drift out of sync on which notification types are clickable.
export function getNotificationLink(
  n: Pick<NotificationDTO, "type" | "reference_type" | "reference_id"> & { metadata?: NotificationDTO["metadata"] },
): string | null {
  if (n.reference_type === "algorithm_job" && n.reference_id) {
    return `/planning/shifts?jobId=${n.reference_id}`;
  }
  if (n.reference_type === "swap_request") {
    if (n.type === "swap_pending_approval") return "/approvals?tab=swaps";
    return (n.type === "swap_offer" || n.type === "swap_offer_incoming") ? "/swaps?tab=incoming" : "/swaps?tab=mine";
  }
  if (n.reference_type === "personal_constraint") {
    return n.type === "constraint_pending" ? "/approvals?tab=constraints" : "/my-requests";
  }
  if (n.reference_type === "exemption_request") {
    if (n.type === "exemption_request_pending") {
      // Cascaded to every commander/DM with visibility over the soldier, which
      // is wider than who can actually decide — the backend tags each
      // recipient's notification with the tab where they'll actually find
      // their item (see exemption_requests.py: _exemption_actionable_check).
      const targetTab = n.metadata?.target_tab;
      return `/approvals?tab=${typeof targetTab === "string" ? targetTab : "exemptions"}`;
    }
    return "/my-requests";
  }
  if (n.reference_type === "hierarchy_transfer_request" && n.type === "transfer_request_pending") {
    return "/approvals?tab=transfers";
  }
  if (n.reference_type === "enrollment_request") {
    return "/approvals?tab=enrollment";
  }
  if (n.reference_type === "duty_assignment") {
    return "/";
  }
  if (n.reference_type === "duty_shift") {
    return "/my-duties";
  }
  if (n.reference_type === "score_adjustment") {
    return "/profile";
  }
  if ((n.reference_type === "range_event" || n.reference_type === "range_assignment") && n.reference_id) {
    return `/ranges?event=${n.reference_id}`;
  }
  if (PROFILE_LINK_TYPES.has(n.type)) {
    return "/profile";
  }
  return null;
}

// Notification types that carry a quick approve/reject decision pair in the
// notification list/dropdown (swap offers and range excusal requests).
export const QUICK_DECISION_TYPES = ["swap_offer_incoming", "range_excusal_pending"] as const;

export function isQuickDecisionNotification(n: Pick<NotificationDTO, "type">): boolean {
  return (QUICK_DECISION_TYPES as readonly string[]).includes(n.type);
}

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

function optionalArrayResponse<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function requiredObjectResponse(value: unknown, errorMessage: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(errorMessage);
  }
  return value as Record<string, unknown>;
}

function requiredNumberField(value: unknown, errorMessage: string): number {
  if (typeof value !== "number") {
    throw new Error(errorMessage);
  }
  return value;
}

export function getUnreadCount(): Promise<UnreadCount> {
  return client.get<unknown>("/notifications/unread-count").then((r) => {
    const data = requiredObjectResponse(r.data, "Invalid unread notifications response");
    return {
      ...data,
      count: requiredNumberField(data.count, "Invalid unread notifications response"),
    } as UnreadCount;
  });
}

export function listNotifications(params?: {
  is_read?: boolean;
  type?: string;
  offset?: number;
  limit?: number;
}): Promise<PaginatedNotifications> {
  return client.get<unknown>("/notifications", { params }).then((r) => {
    const data =
      typeof r.data === "object" && r.data !== null && !Array.isArray(r.data)
        ? (r.data as Record<string, unknown>)
        : {};
    return {
      items: optionalArrayResponse<NotificationDTO>(data.items),
      total: typeof data.total === "number" ? data.total : 0,
    };
  });
}

export function markRead(id: string): Promise<NotificationDTO> {
  return client.patch(`/notifications/${id}/read`).then((r) => r.data);
}

export function markAllRead(): Promise<UnreadCount> {
  return client.patch<unknown>("/notifications/read-all").then((r) => {
    const data = requiredObjectResponse(r.data, "Invalid unread notifications response");
    return {
      ...data,
      count: requiredNumberField(data.count, "Invalid unread notifications response"),
    } as UnreadCount;
  });
}

export function deleteNotification(id: string): Promise<void> {
  return client.delete(`/notifications/${id}`);
}

export function getPreferences(): Promise<NotificationPref[]> {
  return client
    .get<unknown>("/notifications/preferences")
    .then((r) => optionalArrayResponse<NotificationPref>(r.data));
}

export function updatePreferences(preferences: NotificationPref[]): Promise<NotificationPref[]> {
  return client
    .put<unknown>("/notifications/preferences", { preferences })
    .then((r) => optionalArrayResponse<NotificationPref>(r.data));
}

export function listCommanderScopes(): Promise<CommanderScope[]> {
  return client
    .get<unknown>("/notifications/commander-scopes")
    .then((r) => optionalArrayResponse<CommanderScope>(r.data));
}

export function addCommanderScope(hierarchy_node_id: string, depth: number = -1): Promise<CommanderScope> {
  return client.post("/notifications/commander-scopes", { hierarchy_node_id, depth }).then((r) => r.data);
}

export function removeCommanderScope(id: string): Promise<void> {
  return client.delete(`/notifications/commander-scopes/${id}`);
}
