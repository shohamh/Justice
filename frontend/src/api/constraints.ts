import { api } from "./client";
import type { SoldierRef, WaitingOnRef } from "./myRequests";

export interface PersonalConstraint {
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  start_date: string;
  end_date: string;
  reason: string | null;
  status: "pending" | "pending_commander" | "pending_duty_manager" | "approved" | "rejected" | "cancelled";
  commander_approved_by: SoldierRef | null;
  waiting_on: WaitingOnRef | null;
  decided_by: SoldierRef | null;
  requested_at: string;
  updated_at: string;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
  nearest_commander: { id: string; name: string } | null;
  nearest_duty_manager: { id: string; name: string } | null;
  can_approve: boolean;
  can_cancel?: boolean;
}

export async function listMyConstraints(): Promise<PersonalConstraint[]> {
  return (await api.get<PersonalConstraint[]>("/me/constraints")).data;
}

export async function submitConstraint(input: {
  start_date: string;
  end_date: string;
  reason: string;
}): Promise<PersonalConstraint> {
  return (await api.post<PersonalConstraint>("/me/constraints", input)).data;
}

export async function cancelConstraint(id: string, reason?: string): Promise<void> {
  if (reason !== undefined) {
    await api.post(`/constraints/${id}/cancel`, { reason });
    return;
  }
  await api.delete(`/me/constraints/${id}`);
}

export async function cancelConstraintForManager(id: string, reason?: string): Promise<void> {
  await api.post(`/constraints/${id}/cancel`, { reason: reason ?? null });
}

export async function listPendingApprovals(): Promise<PersonalConstraint[]> {
  return (await api.get<PersonalConstraint[]>("/constraints/pending")).data;
}

export async function getPendingCount(): Promise<number> {
  const r = await api.get<{ count: number }>("/constraints/pending/count");
  return r.data.count;
}

export async function approveConstraint(
  id: string,
  note?: string,
): Promise<PersonalConstraint> {
  return (
    await api.post<PersonalConstraint>(`/constraints/${id}/approve`, {
      decision_note: note || null,
    })
  ).data;
}

export async function rejectConstraint(
  id: string,
  note: string,
): Promise<PersonalConstraint> {
  return (
    await api.post<PersonalConstraint>(`/constraints/${id}/reject`, {
      decision_note: note,
    })
  ).data;
}

export async function listSoldierConstraints(
  soldierId: string,
): Promise<PersonalConstraint[]> {
  return (await api.get<PersonalConstraint[]>(`/soldiers/${soldierId}/constraints`)).data;
}

export interface RemainingConstraintDays {
  cap_days: number;
  used_days: number;
  remaining_days: number;
  period_start: string;
  period_end: string;
}

export async function getRemainingConstraintDays(): Promise<RemainingConstraintDays> {
  return (await api.get<RemainingConstraintDays>("/me/constraints/remaining")).data;
}
