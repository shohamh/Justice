import { api } from "./client";
import { ExemptionSummaryItem } from "./exemptions";
import { isRecord, optionalArrayResponse, requiredObjectResponse } from "./responseGuards";

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
  burden_share: number;
  c_over_d: number;
  burden_share_offset_raw: number;
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

export interface BurdenShareContribution {
  kind: "duty" | "adjustment";
  label: string;
  detail: string;
  score: string;
  start_date: string | null; // inclusive, duty spans only
  end_date: string | null;   // inclusive, duty spans only
  days: number;
  multiplier: string;
}

export interface BurdenShareQuarterRow {
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
  contributions: BurdenShareContribution[];
}

export interface BurdenShareBreakdown {
  quarters: BurdenShareQuarterRow[];
  burden_share: string;
  A_i: string;  // Σ(share_q × active_frac_q)
  W_i: string;  // Σ(active_frac_q) — historical weight
}

export async function getTransparency(): Promise<TransparencyOut> {
  const r = await api.get<unknown>(`/scoring/transparency`);
  const data = requiredObjectResponse(r.data, "Invalid transparency response");
  return {
    rows: optionalArrayResponse<TransparencyRow>(data.rows),
    can_see_exemption_aggregates: data.can_see_exemption_aggregates === true,
  };
}

export interface FairnessBurdenShare {
  mean: number; stddev: number; cv: number; min: number; max: number; count: number;
}
export interface FairnessSoldier { soldier_id: string; full_name: string; burden_share: number; eligible_type_count: number; }
export interface FairnessComponent {
  duty_type_names: string[];
  soldier_count: number;
  burden_share: FairnessBurdenShare | null;
  soldiers: FairnessSoldier[];
}
export interface FairnessComponents {
  exempt_from_all: { count: number; soldiers: FairnessSoldier[] };
  components: FairnessComponent[];
}

export async function getFairnessComponents(): Promise<FairnessComponents> {
  const r = await api.get<unknown>(`/scoring/fairness-components`);
  const data = requiredObjectResponse(r.data, "Invalid fairness components response");
  const exemptFromAll = isRecord(data.exempt_from_all) ? data.exempt_from_all : {};
  return {
    exempt_from_all: {
      count: typeof exemptFromAll.count === "number" ? exemptFromAll.count : 0,
      soldiers: optionalArrayResponse<FairnessSoldier>(exemptFromAll.soldiers),
    },
    components: optionalArrayResponse<FairnessComponent>(data.components),
  };
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
  const r = await api.get<unknown>(`/scoring/soldiers/${soldierId}`);
  const data = requiredObjectResponse(r.data, "Invalid score breakdown response");
  return {
    per_type: optionalArrayResponse<Breakdown["per_type"][number]>(data.per_type),
    adjustments: optionalArrayResponse<Breakdown["adjustments"][number]>(data.adjustments),
  };
}
export async function getBurdenShareBreakdown(soldierId: string): Promise<BurdenShareBreakdown> {
  const r = await api.get<unknown>(`/scoring/soldiers/${soldierId}/burden-share-breakdown`);
  const data = requiredObjectResponse(r.data, "Invalid burden-share breakdown response");
  if (typeof data.burden_share !== "string" || typeof data.A_i !== "string" || typeof data.W_i !== "string") {
    throw new Error("Invalid burden-share breakdown response");
  }
  return {
    quarters: optionalArrayResponse<BurdenShareQuarterRow>(data.quarters),
    burden_share: data.burden_share,
    A_i: data.A_i,
    W_i: data.W_i,
  };
}

// Anonymized rank + peer distribution within a soldier's duty-type eligibility
// group. peer_scores carries only burden_share values — never other soldiers'
// names or ids (see backend/app/services/scoring.py::_soldier_burden_share).
export interface BurdenShare {
  has_group: boolean;
  burden_share: number | null;
  rank: number | null;
  group_size: number | null;
  duty_type_names: string[];
  peer_scores: number[];
  mean: number | null;
  stddev: number | null;
  cv: number | null;
  low_sample: boolean;
}

export async function getBurdenShare(soldierId: string): Promise<BurdenShare> {
  const r = await api.get<unknown>(`/scoring/soldiers/${soldierId}/burden-share`);
  const data = requiredObjectResponse(r.data, "Invalid burden share response");
  if (typeof data.has_group !== "boolean") {
    throw new Error("Invalid burden share response");
  }
  return {
    ...(data as unknown as BurdenShare),
    duty_type_names: optionalArrayResponse<string>(data.duty_type_names),
    peer_scores: optionalArrayResponse<number>(data.peer_scores),
  };
}
