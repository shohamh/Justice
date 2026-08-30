import { describe, expect, test, vi } from "vitest";
import { api } from "./client";
import { isSwapActionableForUser, listPendingSwaps, SwapRequest } from "./swaps";

vi.mock("./client");

function makeSwap(overrides: Partial<SwapRequest> = {}): SwapRequest {
  return {
    id: "swap-1",
    duty_assignment_id: "assignment-1",
    duty_date: "2026-08-21",
    requesting_soldier_id: "soldier-1",
    open_to_marketplace: false,
    status: "open",
    reason: null,
    requester_side_approved: null,
    decision_note: null,
    created_at: "2026-08-21T00:00:00Z",
    duty_type_name: null,
    duty_location_name: null,
    duty_type_id: null,
    duty_location_id: null,
    duty_start_date: null,
    duty_end_date: null,
    duty_shift_id: null,
    requester_manager_approvals: [],
    candidates: [],
    ...overrides,
  };
}

function approval(commanderId: string, approverKind: "commander" | "duty_manager") {
  return {
    commander_id: commanderId,
    commander_name: null,
    approved: false,
    approved_by: null,
    approved_by_name: null,
    approved_at: null,
    rejected: false,
    rejected_by: null,
    rejected_by_name: null,
    rejected_at: null,
    approver_kind: approverKind,
  };
}

describe("isSwapActionableForUser", () => {
  test("counts a swap when the viewer is the requester-side commander", () => {
    const swap = makeSwap({ requester_manager_approvals: [approval("viewer-1", "commander")] });

    expect(isSwapActionableForUser(swap, "viewer-1")).toBe(true);
  });

  test("counts a swap when the viewer is the covering-side duty manager for a live candidate", () => {
    const swap = makeSwap({
      candidates: [{
        id: "candidate-1",
        soldier_id: "soldier-2",
        soldier_name: null,
        source: "invited",
        status: "accepted",
        soldier_side_approved: true,
        offered_assignment_ids: [],
        manager_approvals: [approval("viewer-1", "duty_manager")],
      }],
    });

    expect(isSwapActionableForUser(swap, "viewer-1")).toBe(true);
  });

  test("ignores declined candidates and approvals belonging to another viewer", () => {
    const swap = makeSwap({
      requester_manager_approvals: [approval("other-user", "commander")],
      candidates: [{
        id: "candidate-1",
        soldier_id: "soldier-2",
        soldier_name: null,
        source: "marketplace",
        status: "declined",
        soldier_side_approved: false,
        offered_assignment_ids: [],
        manager_approvals: [approval("viewer-1", "commander")],
      }],
    });

    expect(isSwapActionableForUser(swap, "viewer-1")).toBe(false);
  });

  test("counts every swap for an admin", () => {
    expect(isSwapActionableForUser(makeSwap(), "admin-1", true)).toBe(true);
  });
});

describe("listPendingSwaps", () => {
  test("rejects a malformed pending swaps payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listPendingSwaps()).rejects.toThrow("Invalid pending swaps response");
  });

  test("returns the same pending swaps array when the payload is valid", async () => {
    const payload = [makeSwap()];
    vi.mocked(api.get).mockResolvedValue({ data: payload });

    await expect(listPendingSwaps()).resolves.toBe(payload);
  });
});
