import { api } from "./client";
import type { SoldierRef, WaitingOnRef } from "./myRequests";
import { isRecord, optionalArrayResponse, requiredArrayResponse } from "./responseGuards";

export interface ConstraintOverride {
  id: string;
  overridden_by: SoldierRef | null;
  assignment_kind: "duty" | "range";
  reason: string;
  overridden_at: string;
}

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
  commander_approved_at: string | null;
  commander_approval_note?: string | null;
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
  crossed_holidays: { date: string; name: string }[];
  overrides: ConstraintOverride[];
}

/**
 * Normalizes one raw constraint row: drops it if the row itself isn't an
 * object (can't identify it), otherwise keeps every field as-is except the
 * two nested arrays (`overrides`, `crossed_holidays`) which get coerced to
 * `[]` when malformed rather than letting a bad row take down list rendering
 * (UnifiedSoldierModal's `.map`, HolidayBadge's `.map`) for the whole page.
 */
function sanitizeConstraint(raw: unknown): PersonalConstraint | null {
  if (!isRecord(raw)) return null;
  return {
    ...(raw as unknown as PersonalConstraint),
    overrides: optionalArrayResponse<ConstraintOverride>(raw.overrides),
    crossed_holidays: optionalArrayResponse<{ date: string; name: string }>(raw.crossed_holidays),
  };
}

function sanitizeConstraints(value: unknown): PersonalConstraint[] {
  return optionalArrayResponse<unknown>(value)
    .map(sanitizeConstraint)
    .filter((c): c is PersonalConstraint => c !== null);
}

export async function listMyConstraints(): Promise<PersonalConstraint[]> {
  const data = (await api.get<unknown>("/me/constraints")).data;
  return sanitizeConstraints(data);
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
  const data = (await api.get<unknown>("/constraints/pending")).data;
  const arr = requiredArrayResponse<unknown>(data, "Invalid pending constraint approvals response");
  return arr.map(sanitizeConstraint).filter((c): c is PersonalConstraint => c !== null);
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
  const data = (await api.get<unknown>(`/soldiers/${soldierId}/constraints`)).data;
  return sanitizeConstraints(data);
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
