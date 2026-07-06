import { api } from "./client";
import { ExemptionSummaryItem } from "./exemptions";

export interface SoldierPotentialDetail {
  soldier_id: string;
  full_name: string;
  counted: boolean;
  reason: string | null;
  exemption_names: string[] | null;
  rank: string | null;
  partial_exemption_names: string[] | null;
  exemptions: ExemptionSummaryItem[] | null;
}

export interface PotentialModifierDTO {
  id: string;
  delta: number;
  reason: string;
  start_date: string;
  end_date: string | null;
  created_by: string | null;
}

export interface PotentialResult {
  node_id: string;
  as_of: string;
  raw_eligible_count: number;
  total_soldiers: number;
  modifiers: PotentialModifierDTO[];
  final_potential: number;
  soldiers: SoldierPotentialDetail[];
  partial_exemption_count: number;
}

export async function getPotential(nodeId: string, referenceDate?: string): Promise<PotentialResult> {
  return (await api.get<PotentialResult>("/potential", {
    params: { node_id: nodeId, reference_date: referenceDate },
  })).data;
}

export async function listModifiers(nodeId: string): Promise<PotentialModifierDTO[]> {
  return (await api.get<PotentialModifierDTO[]>("/potential/modifiers", {
    params: { hierarchy_node_id: nodeId },
  })).data;
}

export async function createModifier(input: {
  hierarchy_node_id: string; delta: number; reason: string; start_date: string; end_date?: string | null;
}): Promise<PotentialModifierDTO> {
  return (await api.post<PotentialModifierDTO>("/potential/modifiers", input)).data;
}

export async function deleteModifier(modifierId: string): Promise<void> {
  await api.delete(`/potential/modifiers/${modifierId}`);
}

export interface NodeEffortPotential {
  node_id: string;
  node_name: string;
  final_potential: number;
  total_effort: number;
  sibling_potential_share: number | null;
  sibling_effort_share: number | null;
  sibling_gap: number | null;
  global_potential_share: number | null;
  global_effort_share: number | null;
  global_gap: number | null;
}

export async function getEffortGap(referenceDate?: string): Promise<NodeEffortPotential[]> {
  const r = await api.get<{ nodes: NodeEffortPotential[] }>("/potential/effort-gap", {
    params: { reference_date: referenceDate },
  });
  return r.data.nodes;
}
