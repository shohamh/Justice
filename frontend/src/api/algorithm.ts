import { api } from "./client";

export interface SolverSettings {
  K: number;
  T: number;
  W: number;
  alpha: number;
  beta: number;
  time_limit_seconds: number;
}

export interface CreateJobRequest {
  shift_ids: string[];
  mode: "shadow" | "dm_reviewed";
  settings: SolverSettings;
}

export interface ProposalRow {
  assignment_id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  status: string;
  reserve_soldier_id: string | null;
  norm_score_before: number | null;
  norm_score_after: number | null;
  duty_shift_id: string | null;
  candidate_rank: number | null;
  candidate_pool_size: number | null;
}

export interface AlgorithmJob {
  id: string;
  status: "pending" | "running" | "done" | "failed";
  mode: string;
  planning_start: string;
  planning_end: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  proposals: ProposalRow[];
  solver_metrics: Record<string, number>;
  relaxed: string[];
}

export interface SoldierExplanation {
  assigned: boolean;
  norm_score_before: number | null;
  norm_score_after: number | null;
  blocked_count: number;
  tiebreaker_note: string | null;
  global_before: { min_gap: number; norm_variance: number };
  global_after: { min_gap: number; norm_variance: number };
}

export interface DmExplanation {
  duty_id: string;
  assigned_soldier_id: string;
  tiebreaker_note: string | null;
  candidates: Array<{
    soldier_id: string;
    soldier_name: string;
    blocked: boolean;
    blocking_constraints: string[];
    pre_norm_score: number | null;
    post_norm_score: number | null;
  }>;
  global_before: Record<string, number>;
  global_after: Record<string, number>;
}

export async function submitJob(req: CreateJobRequest): Promise<{ id: string; status: string }> {
  return (await api.post<{ id: string; status: string }>("/algorithm/jobs", req)).data;
}

export async function pollJob(jobId: string): Promise<AlgorithmJob> {
  return (await api.get<AlgorithmJob>(`/algorithm/jobs/${jobId}`)).data;
}

export async function getExplanation(
  jobId: string,
  assignmentId: string
): Promise<SoldierExplanation | DmExplanation> {
  return (
    await api.get<SoldierExplanation | DmExplanation>(
      `/algorithm/jobs/${jobId}/explanations/${assignmentId}`
    )
  ).data;
}

export async function getExplanationByAssignment(
  assignmentId: string
): Promise<SoldierExplanation | DmExplanation> {
  return (
    await api.get<SoldierExplanation | DmExplanation>(
      `/algorithm/explanations/${assignmentId}`
    )
  ).data;
}

export async function acceptProposal(jobId: string, assignmentId: string): Promise<void> {
  await api.post(`/algorithm/jobs/${jobId}/proposals/${assignmentId}/accept`);
}

export async function rejectProposal(jobId: string, assignmentId: string): Promise<void> {
  await api.post(`/algorithm/jobs/${jobId}/proposals/${assignmentId}/reject`);
}
