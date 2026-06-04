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
  node_name: string;
  is_reserve: boolean;
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
  return (await api.get<SummaryCards>("/command-dashboard/summary")).data;
}

export async function getDashboardSoldiers(): Promise<SoldierWithStatus[]> {
  return (await api.get<SoldierWithStatus[]>("/command-dashboard/soldiers")).data;
}

export async function getFairnessInternal(): Promise<FairnessStats> {
  return (await api.get<FairnessStats>("/command-dashboard/fairness/internal")).data;
}

export async function getFairnessExternal(): Promise<NodeFairness[]> {
  return (await api.get<NodeFairness[]>("/command-dashboard/fairness/external")).data;
}

export async function getPotential(): Promise<PotentialCount[]> {
  return (await api.get<PotentialCount[]>("/command-dashboard/potential")).data;
}

export async function getUpcoming(): Promise<UpcomingDay[]> {
  return (await api.get<UpcomingDay[]>("/command-dashboard/upcoming")).data;
}

export async function getAlerts(): Promise<Alert[]> {
  return (await api.get<Alert[]>("/command-dashboard/alerts")).data;
}

export async function getApprovals(): Promise<ApprovalItem[]> {
  return (await api.get<ApprovalItem[]>("/command-dashboard/approvals")).data;
}
