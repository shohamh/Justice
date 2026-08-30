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
});
