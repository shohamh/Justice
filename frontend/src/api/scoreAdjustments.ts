import { api } from "./client";

export interface ScoreAdjustment {
  id: string;
  soldier_id: string;
  delta: string;
  reason: string;
  duty_type_id: string | null;
  created_at: string;
}

export async function listAdjustments(soldierId: string): Promise<ScoreAdjustment[]> {
  return (await api.get<ScoreAdjustment[]>(`/score-adjustments`, { params: { soldier_id: soldierId } })).data;
}
export async function createAdjustment(input: { soldier_id: string; delta: string; reason: string; duty_type_id?: string | null }): Promise<ScoreAdjustment> {
  return (await api.post<ScoreAdjustment>(`/score-adjustments`, input)).data;
}

export interface AdjustmentPreview {
  cumulative_score_before: string;
  cumulative_score_after: string;
  normalised_score_before: string;
  normalised_score_after: string;
  burden_share_before: string;
  burden_share_after: string;
}

export async function previewAdjustment(soldierId: string, delta: string): Promise<AdjustmentPreview> {
  return (await api.get<AdjustmentPreview>(`/score-adjustments/preview`, { params: { soldier_id: soldierId, delta } })).data;
}
