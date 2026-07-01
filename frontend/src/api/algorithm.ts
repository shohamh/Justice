import { api } from "./client";

export interface SolverSettings {
  K: number;
  T: number;
  Wt: number;
  R: number;
  Wr: number;
  alpha: number;
  beta: number;
  time_limit_seconds: number;
  num_workers: number;
  auto_relax_node_quotas?: boolean;
}

export interface AlgorithmDefaults {
  T: number;
  Wt: number;
  R: number;
  Wr: number;
}

export interface CreateJobRequest {
  shift_ids: string[];
  mode: "shadow" | "dm_reviewed";
  settings: SolverSettings;
}

export interface BatchShiftFill {
  shift_id: string | null;
  required_count: number;
  assigned_count: number;
}

export interface SaturationClusterCompeting {
  duty_type_id: string;
  count: number;
}

export interface SaturationCluster {
  date_from: string;
  date_to: string;
  shift_ids: string[];
  eligible_pool_size: number;
  free_count: number;
  competing_duty_types: SaturationClusterCompeting[];
}

export interface ImpactedSoldier {
  soldier_id: string;
  soldier_name: string;
  duty_type_name: string;
  start_date: string;
  end_date: string;
  violation: string;
}

export interface BatchResult {
  batch_index: number;
  component_index: number;
  date_from: string;
  date_to: string;
  duty_count: number;
  soldier_count: number;
  assigned_count: number;
  unassigned_count: number;
  outcome: "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "CANCELLED";
  relaxations: string[];
  wall_time_seconds: number;
  shifts: BatchShiftFill[];
  saturation_clusters: SaturationCluster[];
  impacted_soldiers?: ImpactedSoldier[];
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
  batch_index: number | null;
}

export interface CountSpaceStats {
  cv: number | null;
  mean: number | null;
  stddev: number | null;
  min: number | null;
  max: number | null;
  n: number;
}

export interface AlgorithmJob {
  id: string;
  status: "pending" | "running" | "done" | "failed" | "published";
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
  batch_results: BatchResult[];
  result_metadata: {
    fairness_before: CountSpaceStats;
    fairness_after: CountSpaceStats;
    outcome?: "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "CANCELLED";
    objective_value?: number | null;
    solver_metrics?: { wall_time?: number; conflicts?: number; branches?: number };
  } | null;
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
  total_duties: number;
  assigned_duties: number;
  seen: boolean;
}

export interface JobListOut {
  items: JobSummaryOut[];
  total: number;
}

export interface AssignmentContext {
  soldier_name: string;
  duty_type_name: string;
  start_date: string;
  end_date: string;
}

export interface SoldierExplanation {
  assigned: boolean;
  norm_score_before: number | null;
  norm_score_after: number | null;
  blocked_count: number;
  tiebreaker_note: string | null;
  global_before: { min_gap: number; norm_variance: number };
  global_after: { min_gap: number; norm_variance: number };
  assignment_context?: AssignmentContext;
  // Enriched fields for redesigned explanation modal
  score_at_assignment?: number | null;
  eligible_count?: number;
  soldier_rank?: number;
  constraint_count?: number;
  my_constraints?: string[];
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
  assignment_context?: AssignmentContext;
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

export async function markJobSeen(jobId: string): Promise<void> {
  await api.post(`/algorithm/jobs/${jobId}/seen`);
}

export async function markAllJobsSeen(): Promise<void> {
  await api.post("/algorithm/jobs/mark-all-seen");
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

export async function bulkRejectProposals(jobId: string, assignmentIds: string[]): Promise<{ rejected: number }> {
  return (await api.post<{ rejected: number }>(`/algorithm/jobs/${jobId}/proposals/bulk-reject`, { assignment_ids: assignmentIds })).data;
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

export async function retryJob(id: string): Promise<{ id: string; status: string }> {
  return (await api.post<{ id: string; status: string }>(`/algorithm/jobs/${id}/retry`)).data;
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

export async function getAlgorithmDefaults(): Promise<AlgorithmDefaults> {
  return (await api.get<AlgorithmDefaults>("/algorithm/defaults")).data;
}

export async function acceptProposalDirect(assignmentId: string): Promise<void> {
  await api.post(`/algorithm/proposals/${assignmentId}/accept`);
}

export async function rejectProposalDirect(assignmentId: string): Promise<void> {
  await api.post(`/algorithm/proposals/${assignmentId}/reject`);
}
