// frontend/src/api/dutyHistory.ts
import { api } from "./client";
import { requiredArrayResponse } from "./responseGuards";

export interface TimelineEvent {
  id: string;
  event_type:
    | "assignment"
    | "cancellation"
    | "call_up"
    | "dismissal"
    | "exemption"
    | "exemption_request"
    | "personal_constraint"
    | "personal_constraint_override"
    | "range_assignment"
    | "range_removed";
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
  const r = await api.get<unknown>(`/soldiers/${soldierId}/duty-history${params}`);
  return requiredArrayResponse<TimelineEvent>(r.data, "Invalid duty history response");
}
