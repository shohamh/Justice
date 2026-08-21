import { describe, it, expect } from "vitest";
import { isSwapActionable, countActionableSwaps } from "./swapApprovals";
import type { SwapRequest } from "../api/swaps";

function approval(commander_id: string, overrides: Partial<SwapRequest["requester_manager_approvals"][number]> = {}) {
  return {
    commander_id, commander_name: null, approved: false, approved_by: null,
    approved_by_name: null, approved_at: null, rejected: false, rejected_by: null,
    rejected_by_name: null, rejected_at: null, approver_kind: "commander" as const,
    ...overrides,
  };
}

function baseSwap(overrides: Partial<SwapRequest> = {}): SwapRequest {
  return {
    id: "s1", duty_assignment_id: "d1", duty_date: "2026-01-01",
    requesting_soldier_id: "req1", open_to_marketplace: false, status: "open",
    reason: null, requester_side_approved: null, decision_note: null,
    created_at: "2026-01-01T00:00:00Z", duty_type_name: null, duty_location_name: null,
    duty_type_id: null, duty_location_id: null, duty_start_date: null, duty_end_date: null,
    duty_shift_id: null, requester_manager_approvals: [], candidates: [],
    ...overrides,
  };
}

describe("isSwapActionable", () => {
  it("is actionable for the matching requester-side commander", () => {
    const swap = baseSwap({ requester_manager_approvals: [approval("cmd1")] });
    expect(isSwapActionable(swap, { id: "cmd1", isAdmin: false })).toBe(true);
  });

  it("is not actionable for an unrelated commander", () => {
    const swap = baseSwap({ requester_manager_approvals: [approval("cmd1")] });
    expect(isSwapActionable(swap, { id: "cmd2", isAdmin: false })).toBe(false);
  });

  it("is actionable for admins regardless of approver list", () => {
    const swap = baseSwap({ requester_manager_approvals: [approval("cmd1")] });
    expect(isSwapActionable(swap, { id: "anyone", isAdmin: true })).toBe(true);
  });

  it("counts only actionable swaps", () => {
    const mine = baseSwap({ id: "s1", requester_manager_approvals: [approval("cmd1")] });
    const notMine = baseSwap({ id: "s2", requester_manager_approvals: [approval("cmd2")] });
    expect(countActionableSwaps([mine, notMine], { id: "cmd1", isAdmin: false })).toBe(1);
  });
});
