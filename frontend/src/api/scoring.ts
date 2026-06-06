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
  is_officer: boolean | null;
  service_type: "חובה" | "קבע" | null;
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

export function downloadTransparencyExport(nodeId: string | null): void {
  const params = nodeId ? `?node_id=${nodeId}` : "";
  window.location.href = `/api/scoring/transparency/export${params}`;
}

export function downloadSubUnitsExport(): void {
  window.location.href = `/api/scoring/transparency/sub-units/export`;
}
