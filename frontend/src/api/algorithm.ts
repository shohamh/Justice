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
  progress_message: string | null;
  proposals: ProposalRow[];
  solver_metrics: Record<string, number>;
  relaxed: string[];
  reasons: string[];
}

export interface JobSummaryOut {
  id: string;
  status: "pending" | "running" | "done" | "failed";
  mode: string;
  planning_start: string;
  planning_end: string;
  shift_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface JobListOut {
  items: JobSummaryOut[];
  total: number;
}

export interface SoldierExplanation {
  assigned: boolean;
  norm_score_before: number | null;
  norm_score_after: number | null;
  blocked_count: number;
  tiebreaker_note: string | null;
  global_before: { min_gap: number; norm_variance: number };
  global_after: { min_gap: number; norm_variance: number };
  // Enriched fields for redesigned explanation modal
  score_at_assignment?: number | null;
  eligible_count?: number;
  soldier_rank?: number;
  constraint_count?: number;
  ranked_candidates?: Array<{
    soldier_id: string;
    full_name: string;
    score: number | null;
    reason_excluded: string | null;
  }>;
}

export interface CandidateInfo {
  soldier_id: string;
  soldier_name: string | null;
  blocked: boolean;
  blocking_constraints: string[];
  pre_norm_score: number | null;
  post_norm_score: number | null;
}

export interface DmExplanation {
  duty_id: string;
  assigned_soldier_id: string;
  tiebreaker_note: string | null;
  candidates: CandidateInfo[];
  global_before: Record<string, number>;
  global_after: Record<string, number>;
}

export async function submitJob(req: CreateJobRequest): Promise<{ id: string; status: string }> {
  return (await api.post<{ id: string; status: string }>("/algorithm/jobs", req)).data;
}

export async function pollJob(jobId: string): Promise<AlgorithmJob> {
  return (await api.get<AlgorithmJob>(`/algorithm/jobs/${jobId}`)).data;
}

export async function listJobs(limit = 20, offset = 0): Promise<JobListOut> {
  return (await api.get<JobListOut>("/algorithm/jobs", { params: { limit, offset } })).data;
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

export async function bulkAcceptProposals(jobId: string, assignmentIds: string[]): Promise<{ accepted: number }> {
  return (await api.post<{ accepted: number }>(`/algorithm/jobs/${jobId}/proposals/bulk-accept`, { assignment_ids: assignmentIds })).data;
}

export async function rejectProposal(jobId: string, assignmentId: string): Promise<void> {
  await api.post(`/algorithm/jobs/${jobId}/proposals/${assignmentId}/reject`);
}

export async function resetPublished(daysAhead: number): Promise<{ cancelled: number }> {
  return (await api.post<{ cancelled: number }>("/algorithm/reset-published", null, {
    params: { days_ahead: daysAhead },
  })).data;
}

export async function resetDrafts(daysAhead: number): Promise<{ rejected: number }> {
  return (await api.post<{ rejected: number }>("/algorithm/reset-drafts", null, {
    params: { days_ahead: daysAhead },
  })).data;
}

export async function cancelJob(id: string): Promise<void> {
  await api.delete(`/algorithm/jobs/${id}`);
}

export interface DraftPreviewItem {
  assignment_id: string;
  soldier_name: string;
  duty_type_name: string;
  start_date: string;
  end_date: string;
}

export interface DraftsPreviewOut {
  count: number;
  items: DraftPreviewItem[];
}

export async function getDraftsPreview(): Promise<DraftsPreviewOut> {
  return (await api.get<DraftsPreviewOut>("/algorithm/drafts-preview")).data;
}
