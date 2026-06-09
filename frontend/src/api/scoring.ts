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
}

export interface EffortBreakdown {
  quarters: EffortQuarterRow[];
  effort_score: string;
  C_over_D: string;
}

export async function getTransparency(): Promise<TransparencyRow[]> {
  return (await api.get<TransparencyRow[]>(`/scoring/transparency`)).data;
}
export async function getBreakdown(soldierId: string): Promise<Breakdown> {
  return (await api.get<Breakdown>(`/scoring/soldiers/${soldierId}`)).data;
}
export async function getEffortBreakdown(soldierId: string): Promise<EffortBreakdown> {
  return (await api.get<EffortBreakdown>(`/scoring/soldiers/${soldierId}/effort-breakdown`)).data;
}

function _triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function downloadTransparencyExport(nodeId: string | null): Promise<void> {
  const params = nodeId ? `?node_id=${nodeId}` : "";
  try {
    const res = await api.get<Blob>(`/scoring/transparency/export${params}`, { responseType: "blob" });
    _triggerBlobDownload(res.data, "transparency.xlsx");
  } catch (e) {
    console.error("Export failed:", e);
  }
}

export async function downloadSubUnitsExport(): Promise<void> {
  try {
    const res = await api.get<Blob>(`/scoring/transparency/sub-units/export`, { responseType: "blob" });
    _triggerBlobDownload(res.data, "sub-units.xlsx");
  } catch (e) {
    console.error("Export failed:", e);
  }
}
