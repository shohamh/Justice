import { api } from "./client";

export interface DmScopeEntry {
  id: string;
  duty_manager_id: string;
  hierarchy_node_id: string;
}

export async function listDmScope(soldierId: string): Promise<DmScopeEntry[]> {
  return (await api.get<DmScopeEntry[]>("/duty-manager-scope", { params: { soldier_id: soldierId } })).data;
}

export async function assignDmScope(soldierId: string, nodeId: string): Promise<DmScopeEntry> {
  return (await api.post<DmScopeEntry>("/duty-manager-scope", { soldier_id: soldierId, node_id: nodeId })).data;
}

export async function removeDmScope(entryId: string): Promise<void> {
  await api.delete(`/duty-manager-scope/${entryId}`);
}
