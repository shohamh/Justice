import { api } from "./client";
import { requiredArrayResponse } from "./responseGuards";

export interface SwapManagerApproval {
  commander_id: string;
  commander_name: string | null;
  approved: boolean;
  approved_by: string | null;
  approved_by_name: string | null;
  approved_at: string | null;
  decision_note: string | null;
  rejected: boolean;
  rejected_by: string | null;
  rejected_by_name: string | null;
  rejected_at: string | null;
  rejected_note: string | null;
  approver_kind: "commander" | "duty_manager";
}

export interface SwapCandidate {
  id: string;
  soldier_id: string;
  soldier_name: string | null;
  source: "invited" | "marketplace";
  status: "pending" | "declined" | "accepted" | "applied" | "cancelled";
  soldier_side_approved: boolean | null;
  offered_assignment_ids: string[];
  manager_approvals: SwapManagerApproval[];
}

export interface SwapRequest {
  id: string;
  duty_assignment_id: string;
  duty_date: string;
  requesting_soldier_id: string;
  open_to_marketplace: boolean;
  status: "open" | "applied" | "rejected" | "cancelled";
  reason: string | null;
  requester_side_approved: boolean | null;
  decision_note: string | null;
  created_at: string;
  duty_type_name: string | null;
  duty_location_name: string | null;
  duty_type_id: string | null;
  duty_location_id: string | null;
  duty_start_date: string | null;
  duty_end_date: string | null;
  duty_shift_id: string | null;
  warnings?: string[];
  requesting_soldier_name?: string | null;
  requesting_commander_name?: string | null;
  requesting_soldier_node_name?: string | null;
  requester_manager_approvals: SwapManagerApproval[];
  candidates: SwapCandidate[];
}

/** Whether a pending swap has an approval step the viewer can act on. */
export function isSwapActionableForUser(
  swap: SwapRequest,
  userId: string | undefined,
  isAdmin = false,
): boolean {
  if (isAdmin) return true;
  const viewerCanAct = (approvals: SwapManagerApproval[]) => approvals.some((approval) => approval.commander_id === userId);
  if (viewerCanAct(swap.requester_manager_approvals)) return true;
  return swap.candidates.filter((candidate) => candidate.status === "pending" || candidate.status === "accepted").some((candidate) => viewerCanAct(candidate.manager_approvals));
}

export interface CreateSwapInput {
  duty_assignment_id: string;
  target_soldier_id?: string | null;
  target_soldier_ids?: string[];
  open_to_marketplace?: boolean;
  reason?: string | null;
}

export interface EligibleTarget {
  soldier_id: string;
  full_name: string;
  node_name: string | null;
  hierarchy_distance: number;
}

export async function listEligibleTargets(dutyAssignmentId: string): Promise<EligibleTarget[]> {
  return (await api.get<EligibleTarget[]>("/swaps/eligible-targets", {
    params: { duty_assignment_id: dutyAssignmentId },
  })).data;
}

export async function listMySwaps(): Promise<SwapRequest[]> {
  return (await api.get<SwapRequest[]>("/me/swaps")).data;
}

export interface BoardFilters {
  dateFrom?: string;
  dateTo?: string;
  dutyTypeIds?: string[];
  nodeIds?: string[];
  eligibleOnly?: boolean;
}

export async function listBoard(filters?: BoardFilters): Promise<SwapRequest[]> {
  const p = new URLSearchParams();
  if (filters?.dateFrom) p.set("date_from", filters.dateFrom);
  if (filters?.dateTo) p.set("date_to", filters.dateTo);
  for (const id of filters?.dutyTypeIds ?? []) p.append("duty_type_id", id);
  for (const id of filters?.nodeIds ?? []) p.append("node_id", id);
  if (filters?.eligibleOnly) p.set("eligible_only", "true");
  return (await api.get<SwapRequest[]>("/swaps/board", { params: p })).data;
}

export async function createSwap(input: CreateSwapInput): Promise<SwapRequest> {
  return (await api.post<SwapRequest>("/me/swaps", input)).data;
}

export async function addSwapTargets(id: string, targetIds: string[]): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/me/swaps/${id}/targets`, { target_ids: targetIds })).data;
}

export async function publishSwapToMarketplace(id: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/me/swaps/${id}/publish`, {})).data;
}

export async function claimSwap(id: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/claim`, {})).data;
}

export async function cancelSwap(id: string): Promise<void> {
  await api.delete(`/me/swaps/${id}`);
}

export async function listPendingSwaps(): Promise<SwapRequest[]> {
  return requiredArrayResponse<SwapRequest>(
    (await api.get<SwapRequest[]>("/swaps/pending")).data,
    "Invalid pending swaps response",
  );
}

export async function soldierApproveSwap(id: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/me/swaps/${id}/approve`, {})).data;
}

export async function soldierRejectSwap(id: string, decision_note?: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/me/swaps/${id}/reject`, { decision_note })).data;
}

export async function managerApproveSwap(id: string, side: "requester" | "covering", candidateId?: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/manager-approve`, { side, candidate_id: candidateId ?? null })).data;
}

export async function managerRejectSwap(id: string, decision_note?: string, candidateId?: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/manager-reject`, { decision_note, candidate_id: candidateId ?? null })).data;
}

export async function getIncomingSwapCount(): Promise<number> {
  const res = await api.get<{ count: number }>("/swaps/incoming/count");
  return res.data.count;
}

export async function listIncomingSwaps(): Promise<SwapRequest[]> {
  const res = await api.get<SwapRequest[]>("/swaps/incoming");
  return res.data;
}

export async function listSwapsForAssignment(assignmentId: string): Promise<SwapRequest[]> {
  const res = await api.get<SwapRequest[]>(`/swaps/for-assignment/${assignmentId}`);
  return res.data;
}

export async function takeDutyFree(dutyAssignmentId: string): Promise<SwapRequest> {
  const res = await api.post<SwapRequest>("/swaps/take-free", {
    duty_assignment_id: dutyAssignmentId,
  });
  return res.data;
}

export async function getSwapConfig(): Promise<{
  require_manager_approval: boolean;
  require_duty_manager_approval: boolean;
  max_specific_targets: number;
}> {
  return (await api.get<{
    require_manager_approval: boolean;
    require_duty_manager_approval: boolean;
    max_specific_targets: number;
  }>("/swaps/config")).data;
}

export interface EligibilityResult {
  assignment_id: string;
  eligible: boolean;
  reason: string | null;
}

export async function getEligibleDuties(targetSoldierId: string): Promise<EligibilityResult[]> {
  return (await api.get<EligibilityResult[]>("/swaps/eligible-duties", {
    params: { target_soldier_id: targetSoldierId },
  })).data;
}

export async function submitCoverOffer(
  swapId: string,
  offeredAssignmentIds: string[] = [],
): Promise<SwapRequest> {
  const res = await api.post<SwapRequest>(`/swaps/${swapId}/offer`, {
    offered_assignment_ids: offeredAssignmentIds,
  });
  return res.data;
}

export interface CoverEligibilityResult {
  eligible: boolean;
  reason: string | null;
}

export async function checkCoverEligibility(
  assignmentId: string,
): Promise<CoverEligibilityResult> {
  const res = await api.get<CoverEligibilityResult>(
    `/swaps/${assignmentId}/cover-eligibility`,
  );
  return res.data;
}
