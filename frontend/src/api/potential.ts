import { api } from "./client";
import { ExemptionSummaryItem } from "./exemptions";
import { optionalArrayResponse, requiredObjectResponse } from "./responseGuards";

export interface SoldierPotentialDetail {
  soldier_id: string;
  full_name: string;
  counted: boolean;
  reason: string | null;
  exemption_names: string[] | null;
  rank: string | null;
  partial_exemption_names: string[] | null;
  exemptions: ExemptionSummaryItem[] | null;
  eligible_duty_type_ids: string[];
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
  const r = await api.get<unknown>("/potential", {
    params: { node_id: nodeId, reference_date: referenceDate },
  });
  const data = requiredObjectResponse(r.data, "Invalid potential response");
  return {
    ...(data as unknown as PotentialResult),
    modifiers: optionalArrayResponse<PotentialModifierDTO>(data.modifiers),
    soldiers: optionalArrayResponse<SoldierPotentialDetail>(data.soldiers),
  };
}

export async function listModifiers(nodeId: string): Promise<PotentialModifierDTO[]> {
  const r = await api.get<unknown>("/potential/modifiers", {
    params: { hierarchy_node_id: nodeId },
  });
  return optionalArrayResponse<PotentialModifierDTO>(r.data);
}

export async function createModifier(input: {
  hierarchy_node_id: string; delta: number; reason: string; start_date: string; end_date?: string | null;
}): Promise<PotentialModifierDTO> {
  return (await api.post<PotentialModifierDTO>("/potential/modifiers", input)).data;
}

export async function deleteModifier(modifierId: string): Promise<void> {
  await api.delete(`/potential/modifiers/${modifierId}`);
}

export interface NodeBurdenSharePotential {
  node_id: string;
  node_name: string;
  final_potential: number;
  total_burden_share: number;
  sibling_potential_share: number | null;
  sibling_burden_share: number | null;
  sibling_gap: number | null;
  global_potential_share: number | null;
  global_burden_share: number | null;
  global_gap: number | null;
}

export async function getBurdenShareGap(referenceDate?: string): Promise<NodeBurdenSharePotential[]> {
  const r = await api.get<unknown>("/potential/burden-share-gap", {
    params: { reference_date: referenceDate },
  });
  const data = requiredObjectResponse(r.data, "Invalid burden-share-gap response");
  return optionalArrayResponse<NodeBurdenSharePotential>(data.nodes);
}
