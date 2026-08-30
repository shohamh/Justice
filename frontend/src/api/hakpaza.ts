import { api } from "./client";
import { optionalArrayResponse } from "./responseGuards";

export interface Candidate {
  soldier_id: string;
  full_name: string;
  hierarchy_node_name: string;
  hierarchy_distance: number;
  current_score: number;
  score_per_day: number;
  days_remaining: number;
  recent_forced_callups_decayed: number;
}

export interface HakpazaRecord {
  id: string;
  initiator_id: string;
  pulled_soldier_id: string;
  original_assignment_id: string;
  pull_date: string;
  replacement_soldier_id: string;
  replacement_assignment_id: string | null;
  status: "pending" | "approved" | "rejected";
  approver_id: string | null;
  approved_at: string | null;
  callup_multiplier: number;
  created_at: string;
}

export async function findCandidates(pulledAssignmentId: string, pullDate: string, n = 8): Promise<Candidate[]> {
  const data = (await api.post<unknown>("/hakpaza/candidates", {
    pulled_assignment_id: pulledAssignmentId,
    pull_date: pullDate,
    n,
  })).data;
  return optionalArrayResponse<Candidate>(data);
}

export async function createHakpaza(
  pulledAssignmentId: string,
  pullDate: string,
  replacementSoldierId: string,
): Promise<HakpazaRecord> {
  return (await api.post<HakpazaRecord>("/hakpaza", {
    pulled_assignment_id: pulledAssignmentId,
    pull_date: pullDate,
    replacement_soldier_id: replacementSoldierId,
  })).data;
}

export async function approveHakpaza(id: string): Promise<HakpazaRecord> {
  return (await api.post<HakpazaRecord>(`/hakpaza/${id}/approve`, {})).data;
}

export async function rejectHakpaza(id: string): Promise<HakpazaRecord> {
  return (await api.post<HakpazaRecord>(`/hakpaza/${id}/reject`, {})).data;
}

export async function listHakpazot(): Promise<HakpazaRecord[]> {
  return (await api.get<HakpazaRecord[]>("/hakpaza")).data;
}

export async function getPendingHakpazaCount(): Promise<number> {
  return (await api.get<{ count: number }>("/hakpaza/pending-count")).data.count;
}
