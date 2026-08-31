import { api } from "./client";
import { optionalArrayResponse, requiredObjectResponse } from "./responseGuards";

export interface SummaryCards {
  approvals_pending: number;
  upcoming_duties_7d: number;
  unfilled_gaps: number;
  alerts_count: number;
}

export interface SoldierWithStatus {
  id: string;
  personal_number: string;
  full_name: string;
  role: string;
  hierarchy_node_id: string | null;
  status: string;
  cumulative_score: string;
  normalised_score: string;
  enrolled_at: string;
  left_at: string | null;
}

export interface FairnessStats {
  mean: number;
  median: number;
  min: number;
  max: number;
  stddev: number;
  soldier_count: number;
}

export interface NodeFairness {
  node_id: string;
  node_name: string;
  stats: FairnessStats;
}

export interface PotentialCount {
  label: string;
  count: number;
  unit_total: number | null;
}

export interface UpcomingAssignment {
  assignment_id: string;
  soldier_id: string;
  soldier_name: string;
  duty_type_id: string;
  duty_type_name: string;
  duty_location_id: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
  start_time: string;
  end_time: string;
  shift_id: string | null;
  node_name: string;
  is_reserve: boolean;
  status: string;
}

export interface UpcomingDay {
  date: string;
  assignments: UpcomingAssignment[];
}

export interface Alert {
  severity: string;
  soldier_id: string;
  soldier_name: string;
  message: string;
}

export interface ApprovalItem {
  id: string;
  soldier_id: string;
  soldier_name: string;
  request_type: string;
  summary: string;
  created_at: string;
}

export async function getSummary(): Promise<SummaryCards> {
  const r = await api.get<unknown>("/command-dashboard/summary");
  const data = requiredObjectResponse(r.data, "Invalid dashboard summary response");
  if (
    typeof data.approvals_pending !== "number" ||
    typeof data.upcoming_duties_7d !== "number" ||
    typeof data.unfilled_gaps !== "number" ||
    typeof data.alerts_count !== "number"
  ) {
    throw new Error("Invalid dashboard summary response");
  }
  return {
    approvals_pending: data.approvals_pending,
    upcoming_duties_7d: data.upcoming_duties_7d,
    unfilled_gaps: data.unfilled_gaps,
    alerts_count: data.alerts_count,
  };
}

export async function getDashboardSoldiers(): Promise<SoldierWithStatus[]> {
  const data = (await api.get<unknown>("/command-dashboard/soldiers")).data;
  return optionalArrayResponse<SoldierWithStatus>(data);
}

export async function getFairnessInternal(): Promise<FairnessStats> {
  const r = await api.get<unknown>("/command-dashboard/fairness/internal");
  const data = requiredObjectResponse(r.data, "Invalid internal fairness response");
  if (
    typeof data.mean !== "number" ||
    typeof data.median !== "number" ||
    typeof data.min !== "number" ||
    typeof data.max !== "number" ||
    typeof data.stddev !== "number" ||
    typeof data.soldier_count !== "number"
  ) {
    throw new Error("Invalid internal fairness response");
  }
  return {
    mean: data.mean,
    median: data.median,
    min: data.min,
    max: data.max,
    stddev: data.stddev,
    soldier_count: data.soldier_count,
  };
}

export async function getFairnessExternal(): Promise<NodeFairness[]> {
  const data = (await api.get<unknown>("/command-dashboard/fairness/external")).data;
  return optionalArrayResponse<NodeFairness>(data);
}

export async function getPotential(): Promise<PotentialCount[]> {
  const data = (await api.get<unknown>("/command-dashboard/potential")).data;
  return optionalArrayResponse<PotentialCount>(data);
}

export async function getUpcoming(): Promise<UpcomingDay[]> {
  const data = (await api.get<unknown>("/command-dashboard/upcoming")).data;
  return optionalArrayResponse<UpcomingDay>(data);
}

export async function getAlerts(): Promise<Alert[]> {
  const data = (await api.get<unknown>("/command-dashboard/alerts")).data;
  return optionalArrayResponse<Alert>(data);
}

export async function getApprovals(): Promise<ApprovalItem[]> {
  const data = (await api.get<unknown>("/command-dashboard/approvals")).data;
  return optionalArrayResponse<ApprovalItem>(data);
}
