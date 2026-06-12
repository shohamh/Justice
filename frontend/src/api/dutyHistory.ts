// frontend/src/api/dutyHistory.ts
import { api } from "./client";

export interface TimelineEvent {
  id: string;
  event_type:
    | "assignment"
    | "cancellation"
    | "call_up"
    | "dismissal"
    | "exemption_request"
    | "personal_constraint";
  date: string;
  end_date: string | null;
  title: string;
  description: string | null;
  status: string | null;
  metadata: Record<string, string | null>;
  created_at: string;
}

export async function getSoldierDutyHistory(
  soldierId: string,
  includeDrafts?: boolean,
): Promise<TimelineEvent[]> {
  const params = includeDrafts ? "?include_drafts=true" : "";
  return (
    await api.get<TimelineEvent[]>(`/soldiers/${soldierId}/duty-history${params}`)
  ).data;
}
