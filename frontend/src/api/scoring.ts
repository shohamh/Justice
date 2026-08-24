import { api } from "./client";
import { ExemptionSummaryItem } from "./exemptions";

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
  exemptions_display: string;
  exemptions_visible: boolean;
  exemptions: ExemptionSummaryItem[];
  has_global_exemption: boolean | null;
  has_partial_exemption: boolean | null;
  has_temporary_exemption: boolean | null;
}

export interface TransparencyOut {
  rows: TransparencyRow[];
  can_see_exemption_aggregates: boolean;
}

export interface Breakdown {
  per_type: {
    duty_type_id: string;
    duty_type_name: string | null;
    days: number;
    days_past: number;
    days_future: number;
    score: string;
  }[];
  adjustments: { id: string; delta: string; reason: string; created_at: string }[];
}

export interface EffortContribution {
  kind: "duty" | "adjustment";
  label: string;
  detail: string;
  score: string;
  start_date: string | null; // inclusive, duty spans only
  end_date: string | null;   // inclusive, duty spans only
  days: number;
  multiplier: string;
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
  contributions: EffortContribution[];
}

export interface EffortBreakdown {
  quarters: EffortQuarterRow[];
  effort_score: string;
  A_i: string;  // Σ(share_q × active_frac_q)
  W_i: string;  // Σ(active_frac_q) — historical weight
}

export async function getTransparency(): Promise<TransparencyOut> {
  return (await api.get<TransparencyOut>(`/scoring/transparency`)).data;
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

export interface EligibilityGroup {
  duty_type_ids: string[];
  duty_type_names: string[];
  soldier_count: number;
}

export async function listEligibilityGroups(): Promise<EligibilityGroup[]> {
  return (await api.get<EligibilityGroup[]>(`/scoring/eligibility-groups`)).data;
}

export async function getBreakdown(soldierId: string): Promise<Breakdown> {
  return (await api.get<Breakdown>(`/scoring/soldiers/${soldierId}`)).data;
}
export async function getEffortBreakdown(soldierId: string): Promise<EffortBreakdown> {
  return (await api.get<EffortBreakdown>(`/scoring/soldiers/${soldierId}/effort-breakdown`)).data;
}
