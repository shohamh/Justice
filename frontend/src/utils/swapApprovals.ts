import type { SwapRequest } from "../api/swaps";
import { groupByKind, DirectCommanderApprovalRow } from "../components/DirectCommanderApproval";

export interface ApprovalActor {
  id: string;
  isAdmin: boolean;
}

// groupByKind (below) is typed against the minimal DirectCommanderApprovalRow
// shape rather than the full SwapManagerApproval, since it's not generic —
// match that here so the filtered groups it returns typecheck.
function canAct(approvals: DirectCommanderApprovalRow[], actor: ApprovalActor): boolean {
  return actor.isAdmin || approvals.some((a) => a.commander_id === actor.id);
}

/** A swap is "actionable" for this actor if they have standing to approve
 * either the requester side or any live candidate's covering side — either
 * as a matching chain commander/duty-manager, or as an admin (who can act on
 * anything). Mirrors the visibility rule the approvals page uses to split
 * "cards I can decide" from "cards I can only watch." */
export function isSwapActionable(swap: SwapRequest, actor: ApprovalActor): boolean {
  const reqGroups = groupByKind(swap.requester_manager_approvals);
  if (canAct(reqGroups.commander, actor) || canAct(reqGroups.duty_manager, actor)) return true;
  const liveCandidates = swap.candidates.filter((c) => c.status === "pending" || c.status === "accepted");
  return liveCandidates.some((candidate) => {
    const covGroups = groupByKind(candidate.manager_approvals);
    return canAct(covGroups.commander, actor) || canAct(covGroups.duty_manager, actor);
  });
}

export function countActionableSwaps(swaps: SwapRequest[], actor: ApprovalActor): number {
  return swaps.filter((s) => isSwapActionable(s, actor)).length;
}
