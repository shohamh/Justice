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
): Promise<TimelineEvent[]> {
  return (
    await api.get<TimelineEvent[]>(`/soldiers/${soldierId}/duty-history`)
  ).data;
}
