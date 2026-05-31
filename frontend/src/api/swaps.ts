import { api } from "./client";

export interface SwapRequest {
  id: string;
  duty_assignment_id: string;
  duty_date: string;
  requesting_soldier_id: string;
  target_soldier_id: string | null;
  covering_soldier_id: string | null;
  status: "open" | "pending_approval" | "applied" | "rejected" | "cancelled";
  reason: string | null;
  requester_side_approved: boolean | null;
  covering_side_approved: boolean | null;
  decision_note: string | null;
  created_at: string;
}

export interface CreateSwapInput {
  duty_assignment_id: string;
  duty_date: string;
  target_soldier_id?: string | null;
  reason?: string | null;
}

export async function listMySwaps(): Promise<SwapRequest[]> {
  return (await api.get<SwapRequest[]>("/me/swaps")).data;
}

export async function listBoard(): Promise<SwapRequest[]> {
  return (await api.get<SwapRequest[]>("/swaps/board")).data;
}

export async function createSwap(input: CreateSwapInput): Promise<SwapRequest> {
  return (await api.post<SwapRequest>("/me/swaps", input)).data;
}

export async function claimSwap(id: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/claim`, {})).data;
}

export async function cancelSwap(id: string): Promise<void> {
  await api.delete(`/me/swaps/${id}`);
}

export async function listPendingSwaps(): Promise<SwapRequest[]> {
  return (await api.get<SwapRequest[]>("/swaps/pending")).data;
}

export async function approveSwapSide(id: string, side: "requester" | "covering"): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/approve`, { side })).data;
}

export async function rejectSwap(id: string, decision_note?: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/reject`, { decision_note })).data;
}
