import { api } from "./client";

export interface TransferRequest {
  id: string;
  soldier_id: string;
  from_node_id: string | null;
  to_node_id: string;
  status: string;
}

export async function createTransferRequest(soldierId: string, toNodeId: string): Promise<TransferRequest> {
  return (await api.post<TransferRequest>("/hierarchy-transfers", { soldier_id: soldierId, to_node_id: toNodeId })).data;
}

export async function approveTransferRequest(id: string): Promise<TransferRequest> {
  return (await api.post<TransferRequest>(`/hierarchy-transfers/${id}/approve`)).data;
}

export async function rejectTransferRequest(id: string, decisionNote?: string): Promise<TransferRequest> {
  return (await api.post<TransferRequest>(`/hierarchy-transfers/${id}/reject`, { decision_note: decisionNote ?? null })).data;
}

export async function listPendingTransferRequests(): Promise<TransferRequest[]> {
  return (await api.get<TransferRequest[]>("/hierarchy-transfers/pending")).data;
}
