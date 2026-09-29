import { api } from "./client";
import { requiredArrayResponse, requiredObjectResponse, requiredNumberField } from "./responseGuards";

const base = "/admin/exchange-calendar-sync";

export type ExchangeSyncStatus = "queued" | "in_progress" | "synced" | "partial" | "retry_wait" | "failed" | "cancelled";
export type ExchangeSourceType = "duty_shift" | "duty_assignment" | "range_event";
export type ExchangeConnectionErrorCategory = "exchange_unavailable" | "exchange_busy";
export type ExchangeAttendeeRole =
  | "assigned_soldier"
  | "reserve"
  | "called_up_reserve"
  | "direct_commander"
  | "responsible_duty_manager"
  | "contact";

export interface ExchangeSyncCounts {
  eligible: number;
  queued: number;
  in_progress: number;
  synced: number;
  partial: number;
  retry_wait: number;
  failed: number;
}

export interface ExchangeRecentCounts {
  created: number;
  updated: number;
  cancelled: number;
  partial: number;
  failed: number;
}

export interface ExchangeSyncSummary {
  counts: ExchangeSyncCounts;
  recent: ExchangeRecentCounts;
  worker_heartbeat_at: string | null;
  last_probe_at: string | null;
  exchange_reachable: boolean | null;
  last_connection_attempt_at: string | null;
  last_successful_contact_at: string | null;
  latest_connection_error_category: ExchangeConnectionErrorCategory | null;
  latest_connection_error: string | null;
  global_backoff_until: string | null;
}

export interface ExchangeProjectionProblem {
  code: string;
  message: string;
  attendee: ExchangeMissingAttendee | null;
}

export interface ExchangeMissingAttendee {
  name: string;
  role: ExchangeAttendeeRole;
}

export interface ExchangeSyncAttempt {
  outcome: string;
  attempted_at: string;
  error_category: string | null;
  error: string | null;
}

export interface ExchangeSyncEvent {
  source_type: ExchangeSourceType;
  source_id: string;
  source_date: string | null;
  status: ExchangeSyncStatus;
  last_attempt_at: string | null;
  last_success_at: string | null;
  error_category: string | null;
  error: string | null;
  current_projection_problems: ExchangeProjectionProblem[];
  recent_attempts: ExchangeSyncAttempt[];
}

export interface ExchangeSyncEventsPage {
  items: ExchangeSyncEvent[];
  total: number;
  limit: number;
  offset: number;
}

export async function getExchangeSyncSummary(): Promise<ExchangeSyncSummary> {
  const response = await api.get<unknown>(`${base}/summary`);
  return requiredObjectResponse(response.data, "Invalid Exchange sync summary") as unknown as ExchangeSyncSummary;
}

export async function listExchangeSyncEvents(limit = 25, offset = 0): Promise<ExchangeSyncEventsPage> {
  const boundedLimit = Math.max(1, Math.min(100, Math.floor(limit)));
  const boundedOffset = Math.max(0, Math.floor(offset));
  const response = await api.get<unknown>(`${base}/events`, { params: { limit: boundedLimit, offset: boundedOffset } });
  const data = requiredObjectResponse(response.data, "Invalid Exchange sync events");
  return {
    items: requiredArrayResponse<ExchangeSyncEvent>(data.items, "Invalid Exchange sync event items"),
    total: requiredNumberField(data.total, "Invalid Exchange sync event total"),
    limit: requiredNumberField(data.limit, "Invalid Exchange sync event limit"),
    offset: requiredNumberField(data.offset, "Invalid Exchange sync event offset"),
  };
}

export async function retryExchangeSyncEvent(sourceType: ExchangeSourceType, sourceId: string): Promise<{ status: "accepted" }> {
  const response = await api.post<unknown>(`${base}/events/${sourceType}/${encodeURIComponent(sourceId)}/retry`);
  const data = requiredObjectResponse(response.data, "Invalid Exchange sync retry response");
  if (data.status !== "accepted") throw new Error("Invalid Exchange sync retry status");
  return { status: "accepted" };
}
