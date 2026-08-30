import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listMyConstraints, listPendingApprovals, listSoldierConstraints } from "./constraints";

vi.mock("./client");

describe("constraint list APIs", () => {
  it.each([
    ["listMyConstraints", () => listMyConstraints()],
    ["listSoldierConstraints", () => listSoldierConstraints("soldier-1")],
  ])("returns an empty list when %s receives a non-array payload", async (_name, call) => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(call()).resolves.toEqual([]);
  });

  it("rejects a malformed pending approvals payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listPendingApprovals()).rejects.toThrow("Invalid pending constraint approvals response");
  });

  it("drops a non-object row and normalizes a row's malformed nested arrays to [], without touching valid rows", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [
        "not-a-constraint-object",
        {
          id: "c1",
          soldier_id: "s1",
          soldier_name: "Soldier One",
          node_name: null,
          start_date: "2026-08-20",
          end_date: "2026-08-21",
          reason: null,
          status: "pending",
          commander_approved_by: null,
          commander_approved_at: null,
          waiting_on: null,
          decided_by: null,
          requested_at: "2026-08-20T00:00:00Z",
          updated_at: "2026-08-20T00:00:00Z",
          decided_at: null,
          decision_note: null,
          created_at: "2026-08-20T00:00:00Z",
          nearest_commander: null,
          nearest_duty_manager: null,
          can_approve: true,
          crossed_holidays: "not-an-array",
          overrides: { detail: "unexpected" },
        },
      ],
    });

    const result = await listMyConstraints();

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ id: "c1", crossed_holidays: [], overrides: [] });
  });
});
