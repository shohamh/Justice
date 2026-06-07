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
