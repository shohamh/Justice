import { api } from "./client";

export interface TransparencyRow {
  soldier_id: string;
  full_name: string;
  node_name: string | null;
  enrolled_at: string;
  active_days: number;
  cumulative_score: string;
  score_per_day: string;
  normalised_score: string;
}

export interface Breakdown {
  per_type: { duty_type_id: string; duty_type_name: string | null; days: number; score: string }[];
  adjustments: { id: string; delta: string; reason: string; created_at: string }[];
}

export async function getTransparency(): Promise<TransparencyRow[]> {
  return (await api.get<TransparencyRow[]>(`/scoring/transparency`)).data;
}
export async function getBreakdown(soldierId: string): Promise<Breakdown> {
  return (await api.get<Breakdown>(`/scoring/soldiers/${soldierId}`)).data;
}
