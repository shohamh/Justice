import { api } from "./client";

export interface TransparencyRow {
  soldier_id: string;
  full_name: string;
  node_id: string | null;
  node_name: string | null;
  enrolled_at: string;
  active_days: number;
  shift_count: number;
  rank: string | null;
  is_officer: boolean;
  service_type: "חובה" | "קבע" | null;
  cumulative_score: string;
  score_per_day: string;
  normalised_score: string;
  is_globally_exempted: boolean;
  effort_score: number;
  c_over_d: number;
  effort_offset_raw: number;
}

export interface Breakdown {
  per_type: { duty_type_id: string; duty_type_name: string | null; days: number; score: string }[];
  adjustments: { id: string; delta: string; reason: string; created_at: string }[];
}

export interface EffortQuarterRow {
  quarter_start: string;
  quarter_end: string;
  quarter_label: string;
  soldier_score: string;
  unit_score: string;
  active_frac: string;
  share: string;
  weighted_share: string;
  is_partial: boolean;
  adjustment_delta: string;
}

export interface EffortBreakdown {
  quarters: EffortQuarterRow[];
  effort_score: string;
  A_i: string;  // Σ(share_q × active_frac_q)
  W_i: string;  // Σ(active_frac_q) — historical weight
}

export async function getTransparency(): Promise<TransparencyRow[]> {
  return (await api.get<TransparencyRow[]>(`/scoring/transparency`)).data;
}

export interface FairnessEffort {
  mean: number; stddev: number; cv: number; min: number; max: number; count: number;
}
export interface FairnessSoldier { soldier_id: string; full_name: string; effort_score: number; eligible_type_count: number; }
export interface FairnessComponent {
  duty_type_names: string[];
  soldier_count: number;
  effort: FairnessEffort | null;
  soldiers: FairnessSoldier[];
}
export interface FairnessComponents {
  exempt_from_all: { count: number; soldiers: FairnessSoldier[] };
  components: FairnessComponent[];
}

export async function getFairnessComponents(): Promise<FairnessComponents> {
  return (await api.get<FairnessComponents>(`/scoring/fairness-components`)).data;
}
export async function getBreakdown(soldierId: string): Promise<Breakdown> {
  return (await api.get<Breakdown>(`/scoring/soldiers/${soldierId}`)).data;
}
export async function getEffortBreakdown(soldierId: string): Promise<EffortBreakdown> {
  return (await api.get<EffortBreakdown>(`/scoring/soldiers/${soldierId}/effort-breakdown`)).data;
}
