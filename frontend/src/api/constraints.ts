import { api } from "./client";

export interface PersonalConstraint {
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  start_date: string;
  end_date: string;
  reason: string | null;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
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

export async function cancelConstraint(id: string): Promise<void> {
  await api.delete(`/me/constraints/${id}`);
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
