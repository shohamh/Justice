import { api } from "./client";

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

function optionalArrayResponse<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export async function getSummary(): Promise<SummaryCards> {
  return (await api.get<SummaryCards>("/command-dashboard/summary")).data;
}

export async function getDashboardSoldiers(): Promise<SoldierWithStatus[]> {
  const data = (await api.get<unknown>("/command-dashboard/soldiers")).data;
  return optionalArrayResponse<SoldierWithStatus>(data);
}

export async function getFairnessInternal(): Promise<FairnessStats> {
  return (await api.get<FairnessStats>("/command-dashboard/fairness/internal")).data;
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
