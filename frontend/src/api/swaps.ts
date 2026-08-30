import { api } from "./client";
import { isRecord, optionalArrayResponse, requiredArrayResponse } from "./responseGuards";

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

/**
 * Normalizes one raw candidate row: dropped if it isn't an object or is
 * missing the identifying `id`/`soldier_id` fields, otherwise kept as-is
 * except its two nested arrays (`manager_approvals`, `offered_assignment_ids`)
 * which are coerced to `[]` when malformed.
 */
function sanitizeCandidate(raw: unknown): SwapCandidate | null {
  if (!isRecord(raw) || typeof raw.id !== "string" || typeof raw.soldier_id !== "string") return null;
  return {
    ...(raw as unknown as SwapCandidate),
    offered_assignment_ids: optionalArrayResponse<string>(raw.offered_assignment_ids),
    manager_approvals: optionalArrayResponse<SwapManagerApproval>(raw.manager_approvals),
  };
}

/**
 * Normalizes one raw swap row: dropped if it isn't an object or is missing
 * the identifying `id` field (can't render or key a list item without one),
 * otherwise kept as-is except its nested `candidates` and
 * `requester_manager_approvals` arrays, which are individually normalized so
 * one malformed row can't crash `.filter`/`.map` calls (ApprovalsPage,
 * MySwapCard, SwapApprovalColumns) for the whole list.
 */
function sanitizeSwap(raw: unknown): SwapRequest | null {
  if (!isRecord(raw) || typeof raw.id !== "string") return null;
  const candidates = optionalArrayResponse<unknown>(raw.candidates)
    .map(sanitizeCandidate)
    .filter((c): c is SwapCandidate => c !== null);
  return {
    ...(raw as unknown as SwapRequest),
    requester_manager_approvals: optionalArrayResponse<SwapManagerApproval>(raw.requester_manager_approvals),
    candidates,
  };
}

function sanitizeSwaps(value: unknown): SwapRequest[] {
  return optionalArrayResponse<unknown>(value)
    .map(sanitizeSwap)
    .filter((s): s is SwapRequest => s !== null);
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
  const data = (await api.get<unknown>("/swaps/eligible-targets", {
    params: { duty_assignment_id: dutyAssignmentId },
  })).data;
  return optionalArrayResponse<EligibleTarget>(data);
}

export async function listMySwaps(): Promise<SwapRequest[]> {
  const data = (await api.get<unknown>("/me/swaps")).data;
  return sanitizeSwaps(data);
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
  const data = (await api.get<unknown>("/swaps/board", { params: p })).data;
  return sanitizeSwaps(data);
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
  const arr = requiredArrayResponse<unknown>(
    (await api.get<unknown>("/swaps/pending")).data,
    "Invalid pending swaps response",
  );
  return arr.map(sanitizeSwap).filter((s): s is SwapRequest => s !== null);
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
  const res = await api.get<unknown>("/swaps/incoming");
  return sanitizeSwaps(res.data);
}

export async function listSwapsForAssignment(assignmentId: string): Promise<SwapRequest[]> {
  const res = await api.get<unknown>(`/swaps/for-assignment/${assignmentId}`);
  return sanitizeSwaps(res.data);
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
