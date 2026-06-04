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
